"""Slack message templates for the handler's DMs.

Presentation only — these functions take plain data and return mrkdwn strings.
No Slack calls, no decisions about *whether* to notify. That keeps the wording
easy to change without touching moderation logic.
"""

from datetime import datetime, timezone


def format_timestamp(ts):
    """Render a Slack ts ('1712345678.000200') as 'Jul 10, 10:42 AM UTC'."""
    try:
        moment = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return "unknown time"
    # %-d / %-I aren't portable (they fail on Windows), so strip the zero by hand.
    return moment.strftime("%b %d, %I:%M %p UTC").replace(" 0", " ", 1)


def new_member_message(
    name,
    user_id,
    joined_ts,
    workspace=None,
    email=None,
    title=None,
    company=None,
    timezone=None,
    channels_joined=None,
    profile_link=None,
):
    """Body of the '🎉 New Member Joined' DM."""
    lines = [
        "*Name:*",
        name,
        "",
        "*Slack ID:*",
        f"<@{user_id}>",
        "",
        "*Email (if available):*",
        email or "Not available",
        "",
        "*Title:*",
        title or "Not available",
        "",
        "*Company:*",
        company or "Not available",
        "",
        "*Timezone:*",
        timezone or "Not available",
        "",
        "*Channels Joined:*",
        ", ".join(channels_joined or ["Not available"]) if channels_joined else "Not available",
        "",
        "*Join Time:*",
        format_timestamp(joined_ts),
        "",
        "*Profile Link:*",
        profile_link or "Not available",
    ]
    if workspace:
        lines += ["", "*Workspace:*", workspace]
    lines += ["", "Please welcome them to the community."]
    return "\n".join(lines)


def moderation_alert(
    channel_name,
    author_name,
    author_id,
    timestamp,
    text,
    verdict,
    permalink=None,
):
    """Body of the '⚠️ Channel Moderation Alert' DM.

    ``verdict`` is the dict returned by ``moderation.evaluate``. Optional fields
    (suggested channel, suggested reply, permalink) are omitted when absent
    rather than rendered as 'None'.
    """
    author = f"<@{author_id}>" if author_id else f"*{author_name}*"
    confidence = int(round(verdict.get("confidence_score", 0.0) * 100))

    lines = [
        "*Channel:*",
        f"#{channel_name}",
        "",
        "*Posted By:*",
        f"{author_name} ({author})",
        "",
        "*Timestamp:*",
        format_timestamp(timestamp),
        "",
        "*Original Message:*",
        f"> {text}",
        "",
        "*AI Assessment:*",
        f"This message does not appear to match the purpose of #{channel_name}.",
        "",
        "*Reason:*",
        verdict.get("explanation") or "No explanation provided.",
    ]

    if verdict.get("suggested_channel"):
        lines += ["", "*Suggested Channel:*", verdict["suggested_channel"]]

    if verdict.get("suggested_reply"):
        lines += ["", "*Recommended Reply:*", "", verdict["suggested_reply"]]

    lines += ["", "*Confidence:*", f"{confidence}%"]

    if permalink:
        lines += ["", f"<{permalink}|View message in Slack>"]

    # Reinforce, every single time, that the bot did nothing to the user.
    source = verdict.get("source", "ai")
    lines += [
        "",
        f"_Flagged by {source}. Nothing was posted or actioned — you decide._",
    ]
    return "\n".join(lines)


def reply_suggestion(
    channel_name,
    author_name,
    author_id,
    timestamp,
    text,
    suggested_reply,
    permalink=None,
):
    """Body of the '💬 Suggested Reply' DM.

    Surfaces a new channel message plus a draft the handler could send. This is
    independent of moderation — it says nothing about whether the message
    belongs in the channel, only offers a reply the handler may choose to use.
    """
    author = f"<@{author_id}>" if author_id else f"*{author_name}*"

    lines = [
        "*Channel:*",
        f"#{channel_name}",
        "",
        "*Posted By:*",
        f"{author_name} ({author})",
        "",
        "*Timestamp:*",
        format_timestamp(timestamp),
        "",
        "*Message:*",
        f"> {text}",
        "",
        "*Suggested Reply:*",
        "",
        suggested_reply or "No suggestion available.",
    ]

    if permalink:
        lines += ["", f"<{permalink}|View message in Slack>"]

    lines += [
        "",
        "_A suggestion only — nothing was posted. Send it, edit it, or ignore it._",
    ]
    return "\n".join(lines)


def message_relay(
    channel_name,
    author_name,
    author_id,
    timestamp,
    text,
    permalink=None,
    is_thread_reply=False,
):
    """Body of the '📨 New Message' DM — a plain copy of what someone posted.

    No assessment and no draft: this says only that a person posted a message,
    where, and what it said. Deliberately shorter than the other alerts, because
    the handler may receive one of these for every message in the workspace.
    """
    author = f"<@{author_id}>" if author_id else f"*{author_name}*"
    where = f"#{channel_name}" + (" (thread reply)" if is_thread_reply else "")

    lines = [
        "*Channel:*",
        where,
        "",
        "*Posted By:*",
        f"{author_name} ({author})",
        "",
        "*Timestamp:*",
        format_timestamp(timestamp),
        "",
        "*Message:*",
        f"> {text}" if text else "_(no text — see the message in Slack)_",
    ]

    if permalink:
        lines += ["", f"<{permalink}|View message in Slack>"]

    return "\n".join(lines)


def fallback_reply(author_name, channel_name, suggested_channel):
    """A friendly copy-paste reply for the keyword fallback (no AI available)."""
    first_name = (author_name or "there").split()[0]
    where = (
        f"This topic would be a better fit for {suggested_channel}, "
        f"where members are more likely to see it."
        if suggested_channel
        else f"This topic doesn't quite fit what #{channel_name} is for."
    )
    return (
        f"Hi {first_name},\n\n"
        f"Thanks for sharing this.\n\n"
        f"{where}\n\n"
        f"Would you mind reposting it there?\n\n"
        f"Thanks for understanding!"
    )
