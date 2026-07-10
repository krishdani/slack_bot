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

import background
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
# Dispatch
# --------------------------------------------------------------------------- #


def dispatch(client, event):
    """Route a Slack event to its handler, off the request thread.

    Unknown event types are ignored. Returns the name of the handler that was
    queued (useful for logging/tests), or None.
    """
    event_type = event.get("type")

    if event_type == "team_join":
        user = event.get("user")
        user_id = user.get("id") if isinstance(user, dict) else user
        background.submit(process_team_join, client, user_id, event.get("event_ts"))
        return "process_team_join"

    if event_type == "message":
        background.submit(process_message_event, client, event)
        return "process_message_event"

    return None
