"""Business logic for incoming Slack events.

These functions run on background threads (see ``background.py``) so the
``/slack/events`` route can acknowledge within Slack's 3-second budget. Keeping
them here means the route stays a thin transport layer: verify, dedupe, enqueue.

Every handler is defensive: a failure to notify, or a Slack lookup that comes
back empty, is logged and dropped rather than raised.
"""

import logging
import re
import time

import ai
import background
import channel_rules
import config
import moderation
import notify
import store
import templates

logger = logging.getLogger("tpf-community-bot.handlers")

# Only real channel conversations are moderated. This excludes DMs to the bot
# ('im') and group DMs ('mpim'), which are none of the handler's business.
_MODERATED_CHANNEL_TYPES = ("channel", "group")


# --------------------------------------------------------------------------- #
# Feature 1 — a new member joined
# --------------------------------------------------------------------------- #


def _is_noise_message(text):
    """Return True for trivial messages that should never hit the AI."""
    normalized = (text or "").strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered in {"ok", "thanks", "thank you", "+1", "👍", "👎", "🙌", "lol"}:
        return True
    return not re.search(r"[A-Za-z0-9]", normalized)


def process_team_join(client, user_id, event_ts=None):
    """Record a new member and DM the handler in real time.

    The member is recorded first, so the daily report still lists them even if
    the DM fails. The bot never messages the member — the handler welcomes them
    personally.
    """
    if not user_id or user_id == notify.bot_user_id(client):
        return

    # record_member returns False if we've already seen them (Slack retry, or a
    # replayed event), which also stops us DMing the handler twice.
    if not store.record_member(user_id):
        logger.info("team_join_duplicate user=%s (already recorded)", user_id)
        return

    logger.info("team_join user=%s recorded for the daily report", user_id)

    if not config.REALTIME_MEMBER_ALERTS:
        return

    try:
        profile = notify.member_profile_data(client, user_id)
        notify.notify_handler(
            title="🎉 New Member Joined",
            message=templates.new_member_message(
                name=profile.get("name") or notify.display_name_of(client, user_id),
                user_id=user_id,
                joined_ts=event_ts or time.time(),
                workspace=notify.workspace_name(client),
                email=profile.get("email"),
                title=profile.get("title"),
                company=profile.get("company"),
                timezone=profile.get("timezone"),
                channels_joined=profile.get("channels_joined"),
                profile_link=profile.get("profile_link"),
            ),
            priority="normal",
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — alerting should never crash the worker
        logger.exception("team_join_alert_failed user=%s error=%s", user_id, exc)


# --------------------------------------------------------------------------- #
# Feature 2 — AI-powered channel moderation
# --------------------------------------------------------------------------- #


def _skip_reason(client, event):
    """Return why this message shouldn't be moderated, or None to proceed.

    Cheap checks first; the Slack API call (bot id) is last and cached.
    """
    if not config.MODERATION_ENABLED:
        return "moderation_disabled"

    # Joins, edits, deletes, file shares and bot posts all carry a subtype.
    if event.get("subtype") or event.get("bot_id"):
        return "not_a_user_message"

    if event.get("channel_type") not in _MODERATED_CHANNEL_TYPES:
        return "not_a_channel"

    text = (event.get("text") or "").strip()
    if not text:
        return "empty"
    if _is_noise_message(text):
        return "noise"
    if len(text) < config.MODERATION_MIN_CHARS:
        return "too_short"

    # A thread reply's relevance is really its parent's; judging it alone
    # produces false positives ("sounds good!" under an off-topic post).
    thread_ts = event.get("thread_ts")
    if thread_ts and thread_ts != event.get("ts") and not config.MODERATE_THREAD_REPLIES:
        return "thread_reply"

    user_id = event.get("user")
    if not user_id:
        return "no_author"
    if user_id == notify.bot_user_id(client):
        return "own_message"

    return None


def process_message_event(client, event):
    """Moderate one channel message and, if it doesn't belong, DM the handler.

    The message is never stored, never replied to in-channel, and never acted on
    against the author. If it belongs, this function does nothing at all.
    """
    started = time.perf_counter()

    skip = _skip_reason(client, event)
    if skip:
        logger.debug("moderation_skipped reason=%s", skip)
        return

    channel_id = event.get("channel")
    user_id = event.get("user")
    text = (event.get("text") or "").strip()
    ts = event.get("ts")

    channel_name = notify.channel_name_of(client, channel_id)
    author_name = notify.display_name_of(client, user_id)

    logger.info("message_received channel=%s user=%s length=%d", channel_name, user_id, len(text))

    verdict = moderation.evaluate(text, channel_name, author_name)
    if verdict is None:
        logger.debug("moderation_skipped reason=channel_not_configured channel=%s",
                     channel_name)
        return

    elapsed_ms = (time.perf_counter() - started) * 1000

    if not moderation.should_alert(verdict):
        logger.info(
            "moderation_no_action channel=%s belongs=%s confidence=%.2f "
            "threshold=%.2f duration_ms=%d",
            channel_name, verdict["belongs_to_channel"], verdict["confidence_score"],
            config.MODERATION_CONFIDENCE_THRESHOLD, elapsed_ms,
        )
        return

    try:
        notify.notify_handler(
            title="⚠️ Channel Moderation Alert",
            message=templates.moderation_alert(
                channel_name=channel_name,
                author_name=author_name,
                author_id=user_id,
                timestamp=ts,
                text=text,
                verdict=verdict,
                permalink=notify.permalink(client, channel_id, ts),
            ),
            priority="high",
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — alerting should never crash the worker
        logger.exception("moderation_alert_failed channel=%s user=%s error=%s", channel_name, user_id, exc)

    logger.info(
        "moderation_alerted channel=%s author=%s source=%s confidence=%.2f "
        "suggested=%s duration_ms=%d",
        channel_name, user_id, verdict["source"], verdict["confidence_score"],
        verdict["suggested_channel"], (time.perf_counter() - started) * 1000,
    )


# --------------------------------------------------------------------------- #
# Reply suggestions — DM the handler a draft reply for a channel message
# --------------------------------------------------------------------------- #


def _reply_skip_reason(client, event):
    """Return why this message shouldn't get a reply suggestion, or None.

    Deliberately lighter than ``_skip_reason``: by default it only drops things
    a human could never reply to (bot posts, edits/joins, DMs, the bot's own
    messages). Noise/length/thread filtering is opt-in via config, so the
    default is 'draft for every real message'.
    """
    if not config.REPLY_SUGGESTIONS_ENABLED:
        return "reply_suggestions_disabled"

    if event.get("subtype") or event.get("bot_id"):
        return "not_a_user_message"

    if event.get("channel_type") not in _MODERATED_CHANNEL_TYPES:
        return "not_a_channel"

    text = (event.get("text") or "").strip()
    if not text:
        return "empty"  # nothing to reply to
    if len(text) < config.REPLY_SUGGESTIONS_MIN_CHARS:
        return "too_short"

    thread_ts = event.get("thread_ts")
    if (
        thread_ts
        and thread_ts != event.get("ts")
        and not config.REPLY_SUGGESTIONS_INCLUDE_THREADS
    ):
        return "thread_reply"

    user_id = event.get("user")
    if not user_id:
        return "no_author"
    if user_id == notify.bot_user_id(client):
        return "own_message"

    return None


def process_reply_suggestion(client, event):
    """Draft a reply for one channel message and DM it to the handler.

    Runs independently of moderation. If the AI can't produce a suggestion
    (disabled or failed), nothing is sent — an empty draft has no value.
    """
    started = time.perf_counter()

    skip = _reply_skip_reason(client, event)
    if skip:
        logger.debug("reply_suggestion_skipped reason=%s", skip)
        return

    channel_id = event.get("channel")
    user_id = event.get("user")
    text = (event.get("text") or "").strip()
    ts = event.get("ts")

    channel_name = notify.channel_name_of(client, channel_id)
    author_name = notify.display_name_of(client, user_id)

    rules = channel_rules.rules_for(channel_name)
    draft = ai.suggest_reply(text, channel_name, author_name, rules)
    if not draft:
        logger.info(
            "reply_suggestion_none channel=%s user=%s (AI disabled or failed)",
            channel_name, user_id,
        )
        return

    try:
        notify.notify_handler(
            title="💬 Suggested Reply",
            message=templates.reply_suggestion(
                channel_name=channel_name,
                author_name=author_name,
                author_id=user_id,
                timestamp=ts,
                text=text,
                suggested_reply=draft,
                permalink=notify.permalink(client, channel_id, ts),
            ),
            priority="normal",
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — alerting must not crash the worker
        logger.exception(
            "reply_suggestion_failed channel=%s user=%s error=%s",
            channel_name, user_id, exc,
        )

    logger.info(
        "reply_suggestion_sent channel=%s author=%s duration_ms=%d",
        channel_name, user_id, (time.perf_counter() - started) * 1000,
    )


# --------------------------------------------------------------------------- #
# Message relay — DM the handler a copy of every channel message
# --------------------------------------------------------------------------- #

# Subtypes that still mean "a human just posted something". Everything else
# carrying a subtype (channel_join, message_changed, message_deleted, ...) is
# not a new message and is never relayed.
_RELAYABLE_SUBTYPES = (None, "", "file_share", "thread_broadcast", "me_message")


def _relay_skip_reason(client, event):
    """Return why this message shouldn't be relayed, or None to proceed.

    The thinnest gate in the bot. Unlike ``_skip_reason`` and
    ``_reply_skip_reason`` there is no noise filter and no length floor by
    default: the handler asked to see *every* message, so the only things
    dropped are ones that aren't a person posting in a channel — edits, joins,
    DMs to the bot, other apps' posts, and the bot's own alerts.
    """
    if not config.MESSAGE_RELAY_ENABLED:
        return "message_relay_disabled"

    if event.get("subtype") not in _RELAYABLE_SUBTYPES:
        return "not_a_new_message"

    # Another app posted this. Relaying it (including our own DMs, which come
    # back as bot posts) would drown the handler in machine chatter.
    if event.get("bot_id") and not config.MESSAGE_RELAY_INCLUDE_BOTS:
        return "bot_message"

    if event.get("channel_type") not in _MODERATED_CHANNEL_TYPES:
        return "not_a_channel"

    text = (event.get("text") or "").strip()
    if len(text) < config.MESSAGE_RELAY_MIN_CHARS:
        return "too_short"

    thread_ts = event.get("thread_ts")
    if (
        thread_ts
        and thread_ts != event.get("ts")
        and not config.MESSAGE_RELAY_INCLUDE_THREADS
    ):
        return "thread_reply"

    user_id = event.get("user")
    if not user_id:
        return "no_author"
    if user_id == notify.bot_user_id(client):
        return "own_message"

    return None


def process_message_relay(client, event):
    """DM the handler a copy of one channel message. No AI, no judgement.

    Runs independently of moderation and reply suggestions: it reports that a
    person posted, nothing more. A message with no text (a bare file share) is
    still relayed — the permalink is the useful part there.
    """
    started = time.perf_counter()

    skip = _relay_skip_reason(client, event)
    if skip:
        logger.debug("message_relay_skipped reason=%s", skip)
        return

    channel_id = event.get("channel")
    user_id = event.get("user")
    text = (event.get("text") or "").strip()
    ts = event.get("ts")
    thread_ts = event.get("thread_ts")

    channel_name = notify.channel_name_of(client, channel_id)
    author_name = notify.display_name_of(client, user_id)

    try:
        notify.notify_handler(
            title="📨 New Message",
            message=templates.message_relay(
                channel_name=channel_name,
                author_name=author_name,
                author_id=user_id,
                timestamp=ts,
                text=text,
                permalink=notify.permalink(client, channel_id, ts),
                is_thread_reply=bool(thread_ts and thread_ts != ts),
            ),
            priority="normal",
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — alerting must not crash the worker
        logger.exception(
            "message_relay_failed channel=%s user=%s error=%s",
            channel_name, user_id, exc,
        )
        return

    logger.info(
        "message_relayed channel=%s author=%s length=%d duration_ms=%d",
        channel_name, user_id, len(text), (time.perf_counter() - started) * 1000,
    )


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


# Capabilities a route may be limited to. Each optional extra bot claims one and
# the primary keeps the rest; in single-bot mode a route passes capabilities=None
# and does everything.
CAP_JOIN = "join"            # new-member alerts (team_join)
CAP_MODERATION = "moderation"  # channel moderation alerts (message)
CAP_REPLY = "reply"          # AI reply suggestions (message)
CAP_RELAY = "relay"          # copy of every message (message)


def dispatch(client, event, capabilities=None):
    """Route a Slack event to its handler(s), off the request thread.

    Args:
        client: The Slack client to hand the handler — in two-bot mode each
            route passes its own bot's client, so DMs come from the right bot.
        event: The Slack event payload.
        capabilities: Optional set restricting what this route does — any of
            ``CAP_JOIN`` / ``CAP_MODERATION`` / ``CAP_REPLY`` / ``CAP_RELAY``. A
            message can thus drive moderation on one bot, reply-drafting on
            another and relaying on a third. None means do everything
            (single-bot mode).

    Unknown event types are ignored. Returns the name(s) of the handler(s)
    queued (useful for logging/tests), or None.
    """
    event_type = event.get("type")

    def allowed(cap):
        return capabilities is None or cap in capabilities

    if event_type == "team_join":
        if not allowed(CAP_JOIN):
            return None
        user = event.get("user")
        user_id = user.get("id") if isinstance(user, dict) else user
        background.submit(process_team_join, client, user_id, event.get("event_ts"))
        return "process_team_join"

    if event_type == "message":
        # Moderation, reply-suggestion and relay are independent. Each may live
        # on its own bot; in single-bot mode all three run here.
        queued = []
        if allowed(CAP_MODERATION):
            background.submit(process_message_event, client, event)
            queued.append("process_message_event")
        if allowed(CAP_REPLY):
            background.submit(process_reply_suggestion, client, event)
            queued.append("process_reply_suggestion")
        if allowed(CAP_RELAY):
            background.submit(process_message_relay, client, event)
            queued.append("process_message_relay")
        return ",".join(queued) if queued else None

    return None
