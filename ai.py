"""Optional AI message classification via OpenAI, with heuristic fallback.

Two separate jobs live here:

  1. ``classify_messages`` — batch classification at daily-report time.
  2. ``moderate_message`` — single-message, real-time channel moderation.

Job 1 is used ONLY at report time (the daily report), and only when
OPENAI_API_KEY is set. Messages are sent in batches with their channel name so
the model can judge whether each fits its channel and whether it needs a reply —
far better than keywords at spotting "this doesn't belong here".

Token-conscious by design:
  - runs at report time only (not per message, not every day unless you trigger it)
  - batches many messages per request (AI_BATCH_SIZE)
  - truncates long messages and uses a small model (OPENAI_MODEL)

If the key is missing, the openai package isn't installed, or a call fails, the
caller falls back to the keyword heuristics in analysis.py — nothing breaks.
"""

import json
import logging
import os

import channel_rules
import config
from retry import with_retry

logger = logging.getLogger("tpf-community-bot.ai")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
AI_ENABLED = bool(OPENAI_API_KEY) and os.environ.get("AI_CLASSIFICATION", "on").lower() != "off"
BATCH_SIZE = int(os.environ.get("AI_BATCH_SIZE", "40"))
MAX_CHARS = 500  # cap per-message text sent to the model

_client = None

_SYSTEM = (
    "You help a product community manager review Slack. For each message you "
    "get its channel name and text. Judge it against what that channel is for.\n"
    "Return STRICT JSON: {\"results\":[{\"i\":int,\"official\":bool,"
    "\"out_of_place\":string|null,\"needs_reply\":bool}]} with one entry per "
    "input message.\n"
    "- official: true only for genuine announcements, decisions, launches, "
    "action items, or important updates worth surfacing.\n"
    "- out_of_place: a SHORT reason (max ~8 words) if the message does not fit "
    "the channel — e.g. promotion/self-promo in a discussion channel, a support "
    "question in an announcements channel, personal/off-topic chatter in a "
    "focused channel, or spam. Otherwise null.\n"
    "- needs_reply: true if it's a genuine question or request the community "
    "manager would likely want to respond to; false for statements/greetings.\n"
    "Be conservative: when unsure, use null/false. Do not invent entries."
)


def enabled():
    return AI_ENABLED


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI  # imported lazily so it's optional

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _call(payload):
    resp = _get_client().chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps({"messages": payload})},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("results", [])


def classify_messages(messages, channel_name_of):
    """Return a list of verdicts parallel to ``messages``.

    Each verdict is ``{"official": bool, "out_of_place": str | None}``.
    Returns None on any failure / when disabled, so the caller falls back to
    the heuristics.
    """
    if not AI_ENABLED or not messages:
        return None

    verdicts = [None] * len(messages)
    try:
        for start in range(0, len(messages), BATCH_SIZE):
            chunk = messages[start : start + BATCH_SIZE]
            payload = [
                {
                    "i": start + idx,
                    "channel": channel_name_of(m.get("channel_id")),
                    "text": (m.get("text") or "")[:MAX_CHARS],
                }
                for idx, m in enumerate(chunk)
            ]
            for item in _call(payload):
                i = item.get("i")
                if isinstance(i, int) and 0 <= i < len(verdicts):
                    verdicts[i] = {
                        "official": bool(item.get("official")),
                        "out_of_place": item.get("out_of_place") or None,
                        "needs_reply": bool(item.get("needs_reply")),
                    }
    except Exception as e:  # any SDK/network/parse error → fall back
        logger.error("AI classification failed, using heuristics: %s", e)
        return None

    # Anything the model didn't return for → treat as not flagged.
    for i, v in enumerate(verdicts):
        if v is None:
            verdicts[i] = {"official": False, "out_of_place": None, "needs_reply": False}
    logger.info("AI classified %d messages.", len(messages))
    return verdicts


# --------------------------------------------------------------------------- #
# Real-time channel moderation
# --------------------------------------------------------------------------- #

# Longer cap than the batch path: a single message gets the full context budget.
MODERATION_MAX_CHARS = 2000

_MODERATION_SYSTEM = (
    "You are a moderation assistant for a Slack community. You judge whether ONE "
    "message belongs in the channel where it was posted. A human community "
    "manager reviews every judgement you make; you never reply to anyone.\n"
    "\n"
    "Decide using semantic understanding of the author's INTENT, topic, and tone. "
    "Never decide on keywords alone. A message that merely mentions a disallowed "
    "topic is not off-topic — what matters is the purpose the message serves. "
    "Asking 'is anyone else job hunting?' is a discussion; posting a role with a "
    "link and requirements is a job posting.\n"
    "\n"
    "Rules:\n"
    "- Default to correct_channel=true. Return false ONLY when the message "
    "clearly serves a purpose the channel is not for.\n"
    "- Greetings, thanks, short reactions, jokes and casual replies belong "
    "anywhere unless the channel explicitly forbids them.\n"
    "- If the message is ambiguous, truncated, or you cannot tell its intent, "
    "return correct_channel=true with a low confidence. Never guess.\n"
    "- confidence (0.0-1.0) is your confidence in the correct_channel value "
    "you returned. Use scores above 0.9 only when the case is obvious.\n"
    "- reason: one or two plain sentences, grounded ONLY in the message text "
    "and the channel's stated purpose. Never speculate about the author, their "
    "employer, or facts not present in the message. Never invent quotes.\n"
    "- suggested_channel: EXACTLY one channel name from the provided list, or "
    "null. Never invent a channel. Use null when correct_channel is true, or "
    "when no listed channel is a better home for the message.\n"
    "- suggested_reply: a short, warm, professional message the human manager "
    "could copy and send to the author. Address them by first name, thank them, "
    "name the better channel, ask them to repost, thank them for understanding. "
    "Never scold, accuse, or threaten. Use null when correct_channel is true.\n"
    "\n"
    'Return STRICT JSON only, exactly these keys: {"correct_channel": bool, '
    '"confidence": number, "reason": string, "suggested_channel": '
    'string|null, "suggested_reply": string|null}'
)


def _retriable_openai(exc):
    """Retry network blips, rate limits and 5xx — not auth or bad-request errors."""
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status is None:
        return True  # connection reset / timeout / DNS — worth another try
    return status == 429 or status >= 500


def _validate(raw, channel_name):
    """Coerce the model's JSON into the verdict shape, dropping anything unsafe."""
    if isinstance(raw, dict) and "correct_channel" in raw:
        belongs = bool(raw.get("correct_channel", True))
    else:
        belongs = bool(raw.get("belongs_to_channel", True))

    try:
        confidence = float(raw.get("confidence", raw.get("confidence_score", 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    explanation = str(raw.get("reason") or raw.get("explanation") or "").strip()

    # Anti-hallucination: only channels that actually exist in the config survive.
    suggested_channel = channel_rules.resolve_suggested_channel(
        raw.get("suggested_channel")
    )
    if suggested_channel == f"#{channel_name.lstrip('#').lower()}":
        suggested_channel = None  # suggesting the channel it's already in is noise

    suggested_reply = raw.get("suggested_reply")
    suggested_reply = str(suggested_reply).strip() if suggested_reply else None

    if belongs:
        # A "belongs" verdict has nothing to suggest — drop stray fields.
        suggested_channel, suggested_reply = None, None

    return {
        "belongs_to_channel": belongs,
        "confidence_score": confidence,
        "explanation": explanation,
        "suggested_channel": suggested_channel,
        "suggested_reply": suggested_reply,
    }


def moderate_message(text, channel_name, author_name, rules):
    """Ask the model whether one message belongs in its channel.

    Args:
        text: The raw message text.
        channel_name: Channel name without '#'.
        author_name: Display name, so the suggested reply can greet them.
        rules: The channel's entry from ``channel_rules``.

    Returns:
        A verdict dict::

            {"belongs_to_channel": bool, "confidence_score": float,
             "explanation": str, "suggested_channel": str|None,
             "suggested_reply": str|None}

        or None when AI is disabled or every attempt failed — the caller then
        falls back to heuristics.
    """
    if not AI_ENABLED or not (text or "").strip():
        return None

    user_content = json.dumps(
        {
            "channel_rules": channel_rules.describe_channel(channel_name, rules),
            "available_channels": channel_rules.known_channels(),
            "channel_directory": channel_rules.describe_catalog(),
            "author_display_name": author_name,
            "message": text[:MODERATION_MAX_CHARS],
        }
    )

    def _call():
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _MODERATION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    try:
        raw = with_retry(
            _call,
            attempts=config.AI_MAX_RETRIES + 1,
            retriable=_retriable_openai,
            label="openai.moderate_message",
        )
    except Exception as e:  # noqa: BLE001 — any failure means "use heuristics"
        logger.error(
            "moderation_ai_failed channel=%s error=%s (falling back to heuristics)",
            channel_name, e,
        )
        return None

    if not isinstance(raw, dict):
        logger.error("moderation_ai_bad_shape channel=%s payload=%r", channel_name, raw)
        return None

    return _validate(raw, channel_name)


# --------------------------------------------------------------------------- #
# Reply suggestions
# --------------------------------------------------------------------------- #

_REPLY_SYSTEM = (
    "You draft replies for a product-community manager on Slack. You are given "
    "one message, the name of the channel it was posted in, and what that "
    "channel is for. Draft a single reply the manager could send in that "
    "channel.\n"
    "\n"
    "The manager reviews every draft and decides whether to send it — you never "
    "post anything yourself.\n"
    "\n"
    "Guidance:\n"
    "- Be warm, concise and genuinely helpful. Sound like a real person, not a "
    "form letter. One short paragraph is usually enough.\n"
    "- Address the author by first name when it reads naturally.\n"
    "- If it's a question, actually try to answer or point them in the right "
    "direction. If it's a statement or greeting, a brief acknowledgement is "
    "fine.\n"
    "- Never invent facts, links, dates, prices or commitments. If you don't "
    "know something, say the manager will follow up rather than guessing.\n"
    "- No @-mentions, no channel links, no markdown headings — just the message "
    "text the manager would type.\n"
    "\n"
    'Return STRICT JSON only, exactly this key: {"suggested_reply": string}'
)


def suggest_reply(text, channel_name, author_name, rules=None):
    """Draft a reply the handler could send to one channel message.

    Args:
        text: The raw message text.
        channel_name: Channel name without '#'.
        author_name: Display name, so the draft can greet them.
        rules: The channel's entry from ``channel_rules`` (for context), or None.

    Returns:
        A non-empty draft string, or None when AI is disabled, the message is
        empty, or every attempt failed. A None return means "no suggestion" —
        the caller skips the DM rather than sending an empty one.
    """
    if not AI_ENABLED or not (text or "").strip():
        return None

    user_content = json.dumps(
        {
            "channel": channel_name,
            "channel_purpose": (rules or {}).get("purpose"),
            "author_display_name": author_name,
            "message": text[:MODERATION_MAX_CHARS],
        }
    )

    def _call():
        resp = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.3,  # a little warmth; replies shouldn't read robotic
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _REPLY_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    try:
        raw = with_retry(
            _call,
            attempts=config.AI_MAX_RETRIES + 1,
            retriable=_retriable_openai,
            label="openai.suggest_reply",
        )
    except Exception as e:  # noqa: BLE001 — any failure means "no suggestion"
        logger.error(
            "reply_ai_failed channel=%s error=%s (no suggestion sent)",
            channel_name, e,
        )
        return None

    if not isinstance(raw, dict):
        logger.error("reply_ai_bad_shape channel=%s payload=%r", channel_name, raw)
        return None

    reply = raw.get("suggested_reply")
    reply = str(reply).strip() if reply else ""
    return reply or None
