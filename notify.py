"""Helpers for giving the Human POC context via direct message.

Everything the bot surfaces goes to a single configured POC as a DM. The bot
never messages members or channels on its own — it only informs the POC, who
takes any user-facing action personally.

``dm_poc`` (daily report) and ``notify_handler`` (real-time alerts) both deliver
to the same person; ``notify_handler`` is the general-purpose entry point used
by the new alerting features.
"""

import logging
import os

from slack_sdk.errors import SlackApiError

import config
from retry import with_retry

logger = logging.getLogger("tpf-community-bot.notify")

HUMAN_POC_USER_ID = os.environ.get("HUMAN_POC_USER_ID")

# The handler who receives real-time alerts. Same person as the POC above;
# config accepts either env var name and prefers HANDLER_SLACK_USER.
HANDLER_USER_ID = config.HANDLER_SLACK_USER

# Simple in-memory caches so we don't call Slack for the same name repeatedly.
# Dict writes are atomic under the GIL, so these are safe to share between the
# Flask request threads and the background workers.
_user_cache = {}
_channel_cache = {}
_workspace_name = None
_bot_user_id = None

# Prefixes that let the handler triage a DM at a glance.
_PRIORITY_PREFIX = {"normal": "", "high": "", "urgent": "🚨 "}


def _retriable_slack(exc):
    """Retry rate limits, 5xx and transport errors — never auth/permission errors."""
    if not isinstance(exc, SlackApiError):
        return True  # connection reset / timeout — worth another try
    status = getattr(exc.response, "status_code", None)
    return status == 429 or (status is not None and status >= 500)


def _slack_delay_hint(exc):
    """Honour Slack's Retry-After header when it rate-limits us."""
    if isinstance(exc, SlackApiError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return None


def _profile_field(profile, *keys):
    for key in keys:
        value = profile.get(key)
        if value:
            return value
    return None


def member_profile_data(client, user_id):
    """Best-effort Slack profile enrichment for new-member alerts."""
    profile = {
        "name": "unknown",
        "email": None,
        "title": None,
        "company": None,
        "timezone": None,
        "channels_joined": [],
        "profile_link": None,
    }
    if not user_id:
        return profile

    try:
        info = client.users_info(user=user_id).get("user", {})
        profile_data = info.get("profile", {})
        profile["name"] = (
            profile_data.get("display_name")
            or profile_data.get("real_name")
            or info.get("name")
            or user_id
        )
        profile["email"] = _profile_field(profile_data, "email")
        profile["title"] = _profile_field(profile_data, "title")
        profile["company"] = _profile_field(profile_data, "company")
        profile["timezone"] = _profile_field(profile_data, "tz", "tz_label")
        team_id = info.get("team_id")
        if team_id:
            profile["profile_link"] = f"https://app.slack.com/client/{team_id}/{user_id}"
    except SlackApiError as e:
        logger.warning("users_info failed for %s: %s", user_id, e.response.get("error"))

    try:
        resp = client.users_conversations(
            user=user_id,
            types="public_channel,private_channel",
            limit=100,
        )
        profile["channels_joined"] = [
            channel.get("name") or channel.get("id")
            for channel in resp.get("channels", [])
            if channel.get("name") or channel.get("id")
        ]
    except Exception as e:  # noqa: BLE001 — best-effort enrichment only
        logger.debug("users_conversations failed for %s: %s", user_id, e)

    return profile


def display_name_of(client, user_id):
    """Return a readable name for a user id, cached. Falls back to the id."""
    if not user_id:
        return "unknown"
    if user_id in _user_cache:
        return _user_cache[user_id]
    name = user_id
    try:
        info = client.users_info(user=user_id).get("user", {})
        profile = info.get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or info.get("name")
            or user_id
        )
    except SlackApiError as e:
        logger.warning("users_info failed for %s: %s", user_id, e.response.get("error"))
    _user_cache[user_id] = name
    return name


def channel_name_of(client, channel_id):
    """Return a readable channel name for a channel id, cached."""
    if not channel_id:
        return "unknown"
    if channel_id in _channel_cache:
        return _channel_cache[channel_id]
    name = channel_id
    try:
        info = client.conversations_info(channel=channel_id).get("channel", {})
        name = info.get("name") or channel_id
    except SlackApiError as e:
        logger.warning(
            "conversations_info failed for %s: %s", channel_id, e.response.get("error")
        )
    _channel_cache[channel_id] = name
    return name


def bot_user_id(client):
    """Return (and cache) the bot's own Slack user id, or None if unavailable."""
    global _bot_user_id
    if _bot_user_id is None:
        try:
            _bot_user_id = client.auth_test().get("user_id")
        except SlackApiError as e:
            logger.error("auth.test failed: %s", e.response.get("error"))
    return _bot_user_id


def workspace_name(client):
    """Return (and cache) the workspace name, or None. Needs the team:read scope."""
    global _workspace_name
    if _workspace_name is None:
        try:
            _workspace_name = client.team_info().get("team", {}).get("name")
        except SlackApiError as e:
            logger.warning("team.info failed: %s", e.response.get("error"))
    return _workspace_name


def permalink(client, channel_id, message_ts):
    """Best-effort deep link to a message, so the handler can jump straight to it."""
    try:
        return client.chat_getPermalink(
            channel=channel_id, message_ts=message_ts
        ).get("permalink")
    except SlackApiError as e:
        logger.warning("chat.getPermalink failed: %s", e.response.get("error"))
        return None


def dm_user(client, user_id, text):
    """Open (or reuse) a DM with a user and post a message. Returns True/False.

    Transient failures (rate limits, 5xx, dropped connections) are retried with
    backoff. A permanent failure is logged and returns False — it never raises,
    because a failed notification must not take down the caller.
    """
    if not user_id:
        return False

    def _send():
        im = client.conversations_open(users=user_id)
        client.chat_postMessage(
            channel=im["channel"]["id"],
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )

    try:
        with_retry(
            _send,
            attempts=config.SLACK_MAX_RETRIES,
            retriable=_retriable_slack,
            delay_hint=_slack_delay_hint,
            label=f"slack.dm[{user_id}]",
        )
        return True
    except SlackApiError as e:
        logger.error("dm_failed user=%s error=%s", user_id, e.response.get("error"))
        return False
    except Exception as e:  # noqa: BLE001 — transport errors must not crash the worker
        logger.error("dm_failed user=%s error=%s", user_id, e)
        return False


def dm_poc(client, text):
    """Send a direct message to the configured Human POC."""
    if not HUMAN_POC_USER_ID:
        logger.warning("HUMAN_POC_USER_ID is not set — cannot notify the POC.")
        return False
    return dm_user(client, HUMAN_POC_USER_ID, text)


def notify_handler(title, message, priority="normal", client=None):
    """DM the configured community handler. The one entry point for alerts.

    Args:
        title: Short headline, e.g. '⚠️ Channel Moderation Alert'.
        message: Pre-rendered mrkdwn body (see ``templates``).
        priority: 'normal' | 'high' | 'urgent'. Affects the visual prefix and
            the log level, never the destination.
        client: Slack client; defaults to the shared one from ``config``.

    Returns:
        True if Slack accepted the message, False otherwise. Never raises, so a
        notification failure can't break the event being processed.
    """
    if not HANDLER_USER_ID:
        logger.warning(
            "notify_skipped title=%r reason=no_handler_configured "
            "(set HANDLER_SLACK_USER or HUMAN_POC_USER_ID)",
            title,
        )
        return False

    client = client or config.get_slack_client()
    prefix = _PRIORITY_PREFIX.get(priority, "")
    delivered = dm_user(client, HANDLER_USER_ID, f"{prefix}*{title}*\n\n{message}")

    log = logger.info if delivered else logger.error
    log(
        "notify_handler title=%r priority=%s delivered=%s",
        title, priority, delivered,
    )
    return delivered
