"""Telegram alerts for channel messages the relay recipient hasn't replied to.

Triggered by ``/tasks/unreplied-check`` (pinged by cron-job.org every 15 min).
Each check reads recent history in every channel the bot is in. A message is
unreplied while MESSAGE_RELAY_USER_ID (Khushi) hasn't posted in its thread
after it; once that has lasted UNREPLIED_AFTER_HOURS, the message is sent to
UNREPLIED_TELEGRAM_CHAT_ID — once, tracked in ``store``.

Telegram, not email: Render's free plan blocks outbound SMTP, but Telegram's
Bot API is plain HTTPS.

Run locally:
    python unreplied.py --dry-run   # print what would be sent; send nothing
    python unreplied.py --chat-ids  # list chats that messaged the Telegram bot
"""

import html
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from slack_sdk.errors import SlackApiError

import collect
import config
import notify
import store

logger = logging.getLogger("tpf-community-bot.unreplied")

# Only one check at a time — overlapping cron pings must not double-alert.
_check_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Finding unreplied messages
# --------------------------------------------------------------------------- #


def _is_human(message):
    return bool(message.get("user")) and not message.get("bot_id") and (
        message.get("subtype") in (None, "thread_broadcast", "file_share")
    )


def first_unreplied(thread_messages, recipient_id):
    """Return the oldest message in a thread posted after the recipient last spoke.

    ``thread_messages`` is the parent followed by its replies, oldest first. The
    recipient's own messages are never "unreplied". Returns None when the
    recipient has the last word (or nobody else has posted).
    """
    last_reply_at = None
    for i, m in enumerate(thread_messages):
        if m.get("user") == recipient_id:
            last_reply_at = i
    after = thread_messages if last_reply_at is None else thread_messages[last_reply_at + 1:]
    for m in after:
        if _is_human(m) and m.get("user") != recipient_id:
            return m
    return None


def _thread(client, channel_id, parent):
    """The parent plus all its replies, oldest first."""
    if not parent.get("reply_count"):
        return [parent]
    messages, cursor = [], None
    while True:
        params = {"channel": channel_id, "ts": parent["ts"], "limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = client.conversations_replies(**params)
        messages.extend(resp.get("messages", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not resp.get("has_more") or not cursor:
            return messages


def find_unreplied(client, recipient_id, now=None):
    """Return messages that went unreplied-overdue within the alert window.

    Each item is ``{channel_id, ts, user_id, text, is_thread_reply}``.
    """
    now = now or time.time()
    overdue_before = now - config.UNREPLIED_AFTER_HOURS * 3600
    overdue_since = overdue_before - config.UNREPLIED_ALERT_WINDOW_HOURS * 3600
    oldest = now - config.UNREPLIED_LOOKBACK_HOURS * 3600

    found = []
    for channel_id in collect._member_channels(client):
        for parent in collect._channel_history(client, channel_id, oldest):
            parent = {"user": parent["user_id"], **parent}
            try:
                thread = _thread(client, channel_id, parent)
            except SlackApiError as e:
                logger.warning(
                    "unreplied_replies_failed channel=%s ts=%s error=%s",
                    channel_id, parent["ts"], e.response.get("error"),
                )
                continue
            m = first_unreplied(thread, recipient_id)
            if m and overdue_since <= float(m["ts"]) < overdue_before:
                found.append({
                    "channel_id": channel_id,
                    "ts": m["ts"],
                    "user_id": m.get("user"),
                    "text": m.get("text", ""),
                    "is_thread_reply": m["ts"] != parent["ts"],
                })
    return found


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #

_IST = timezone(timedelta(hours=5, minutes=30))
_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")
_CHANNEL = re.compile(r"<#[A-Z0-9]+\|([^>]*)>")
_TELEGRAM_LIMIT = 4096


def format_ist(ts):
    """Render a Slack ts as 'Oct 14, 4:35 PM IST' — the recipient reads IST."""
    moment = datetime.fromtimestamp(float(ts), tz=_IST)
    return moment.strftime("%b %d, %I:%M %p IST").replace(" 0", " ", 1)


def _plain(client, text):
    """Turn Slack markup into readable plain text."""
    text = _MENTION.sub(lambda m: "@" + notify.display_name_of(client, m.group(1)), text or "")
    text = _CHANNEL.sub(lambda m: "#" + m.group(1), text)
    text = _LINK.sub(lambda m: m.group(2) or m.group(1), text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def alert_text(client, item):
    """The Telegram message (HTML parse mode) for one unreplied message."""
    channel = notify.channel_name_of(client, item["channel_id"])
    where = f"#{channel}" + (" (thread reply)" if item["is_thread_reply"] else "")
    author = notify.display_name_of(client, item["user_id"])
    body = _plain(client, item["text"]).strip() or "(no text — see it in Slack)"
    if len(body) > 3000:
        body = body[:3000] + "…"
    lines = [
        f"⏰ <b>No reply for {config.UNREPLIED_AFTER_HOURS:g}+ hours</b>",
        "",
        f"<b>{html.escape(where, quote=False)}</b> · {html.escape(author, quote=False)} · {format_ist(item['ts'])}",
        "",
        html.escape(body, quote=False),
    ]
    link = notify.permalink(client, item["channel_id"], item["ts"])
    if link:
        lines += ["", f'<a href="{html.escape(link)}">Open in Slack</a>']
    return "\n".join(lines)[:_TELEGRAM_LIMIT]


def _telegram(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_telegram(text):
    """Send one message to the configured chat. Returns True/False, never raises."""
    try:
        result = _telegram("sendMessage", {
            "chat_id": config.UNREPLIED_TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
        return bool(result.get("ok"))
    except Exception as exc:  # noqa: BLE001 — a failed alert must not crash the check
        logger.error("telegram_send_failed error=%s", exc)
        return False


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #


def run_check(client, dry_run=False):
    """Find overdue unreplied messages and alert each one once.

    Returns a summary dict. Skips (returns ``skipped``) if a check is already
    running or the feature isn't configured.
    """
    recipient_id = config.MESSAGE_RELAY_USER_ID
    if not dry_run and not config.UNREPLIED_ALERTS_ENABLED:
        return {"skipped": "not_configured"}
    if not recipient_id:
        return {"skipped": "no_recipient"}
    if not _check_lock.acquire(blocking=False):
        return {"skipped": "already_running"}
    try:
        items = [
            i for i in find_unreplied(client, recipient_id)
            if not store.was_alerted(i["channel_id"], i["ts"])
        ]
        sent = 0
        for item in items:
            text = alert_text(client, item)
            if dry_run:
                print(text, end="\n\n---\n\n")
                continue
            if send_telegram(text):
                store.mark_alerted(item["channel_id"], item["ts"])
                sent += 1
        logger.info("unreplied_check found=%d sent=%d dry_run=%s", len(items), sent, dry_run)
        return {"found": len(items), "sent": sent}
    finally:
        _check_lock.release()


def _print_chat_ids():
    """List the chats that have messaged the Telegram bot (for setup)."""
    updates = _telegram("getUpdates", {}).get("result", [])
    chats = {}
    for u in updates:
        chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("first_name") or chat.get("title")
    if not chats:
        print("No chats yet — open the bot in Telegram, press Start, then rerun.")
    for chat_id, name in chats.items():
        print(f"{chat_id}\t{name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unreplied-message Telegram alerts")
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    parser.add_argument("--chat-ids", action="store_true", help="list chats that messaged the bot")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.chat_ids:
        _print_chat_ids()
    else:
        store.init_db()
        slack = (
            config.get_relay_slack_client() if config.RELAY_BOT_MODE
            else config.get_slack_client()
        )
        print(run_check(slack, dry_run=args.dry_run))
