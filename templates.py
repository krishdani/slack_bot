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


def new_member_message(name, user_id, joined_ts, workspace=None):
    """Body of the '🎉 New Member Joined' DM (joined the workspace)."""
    lines = [
        "*Name:*",
        name,
        "",
        "*Mention:*",
        f"<@{user_id}>",
        "",
        "*Joined:*",
        format_timestamp(joined_ts),
    ]
    if workspace:
        lines += ["", "*Workspace:*", workspace]
    lines += ["", "Please welcome them to the community."]
    return "\n".join(lines)


def channel_join_message(
    name,
    user_id,
    channel_name,
    channel_id,
    joined_ts,
    inviter_id=None,
):
    """Body of the '👋 New Member in #channel' DM (joined a single channel).

    ``inviter_id`` is present only when someone invited them; a self-join (or a
    join via a shared link) carries no inviter, so we omit the line entirely
    rather than rendering 'None'.
    """
    channel = f"<#{channel_id}|{channel_name}>" if channel_id else f"#{channel_name}"

    lines = [
        "*Name:*",
        name,
        "",
        "*Mention:*",
        f"<@{user_id}>",
        "",
        "*Channel:*",
        channel,
        "",
        "*Joined:*",
        format_timestamp(joined_ts),
    ]
    if inviter_id:
        lines += ["", "*Invited By:*", f"<@{inviter_id}>"]
    lines += ["", f"Please welcome them to #{channel_name}."]
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
