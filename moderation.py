"""Decide whether a message belongs in its channel.

The AI path (``ai.moderate_message``) is tried first. If OpenAI is disabled,
unreachable, or returns something unusable, we fall back to the keyword
``redirects`` in ``channel_rules`` and, failing those, the existing
``analysis.classify_message`` heuristics. The bot therefore keeps moderating
even with no API key at all — just less precisely.

This module decides; it never sends anything. Delivery lives in ``notify``.

Confidence scale (shared by both paths, compared against
``config.MODERATION_CONFIDENCE_THRESHOLD``, default 0.7):

    AI            model's own score, validated and clamped to 0.0-1.0
    0.80          a configured redirect phrase matched — a strong, explicit signal
    0.60          generic heuristic flag — deliberately below the default
                  threshold, so weak keyword guesses inform the daily report
                  but do not page the handler in real time
"""

import logging

import ai
import analysis
import channel_rules
import config
import templates

logger = logging.getLogger("tpf-community-bot.moderation")


def _belongs(confidence=0.5):
    """A 'nothing to see here' verdict."""
    return {
        "belongs_to_channel": True,
        "confidence_score": confidence,
        "explanation": "",
        "suggested_channel": None,
        "suggested_reply": None,
    }


def _heuristic(text, channel_name, rules, author_name):
    """Keyword fallback used when the AI is unavailable.

    First tries the channel's configured ``redirects`` (explicit, high signal),
    then the project's pre-existing generic heuristics (weak signal).
    """
    low = (text or "").lower()

    for rule in rules.get("redirects", []):
        if any(phrase in low for phrase in rule["phrases"]):
            suggested = channel_rules.resolve_suggested_channel(rule.get("suggested_channel"))
            return {
                "belongs_to_channel": False,
                "confidence_score": 0.8,
                "explanation": (
                    f"The message appears to be {rule['reason']}, while "
                    f"#{channel_name} is intended for {rules['purpose'].rstrip('.').lower()}."
                ),
                "suggested_channel": suggested,
                "suggested_reply": templates.fallback_reply(
                    author_name, channel_name, suggested
                ),
            }

    # Reuse the daily report's heuristics rather than writing a second copy.
    verdict = analysis.classify_message(text, channel_name)
    if verdict.get("out_of_place"):
        return {
            "belongs_to_channel": False,
            "confidence_score": 0.6,
            "explanation": verdict["out_of_place"],
            "suggested_channel": None,
            "suggested_reply": templates.fallback_reply(author_name, channel_name, None),
        }

    return _belongs()


def evaluate(text, channel_name, author_name):
    """Judge one message against its channel's rules.

    Returns a verdict dict with an extra ``source`` key ('ai' or 'heuristic'),
    or None when the channel isn't moderated at all (no rules configured and
    ``MODERATE_UNCONFIGURED_CHANNELS`` is off).
    """
    rules = channel_rules.rules_for(channel_name)
    if rules is None:
        if not config.MODERATE_UNCONFIGURED_CHANNELS:
            return None
        rules = channel_rules.GENERIC_RULE

    verdict = ai.moderate_message(text, channel_name, author_name, rules)
    source = "ai"

    if verdict is None:
        verdict = _heuristic(text, channel_name, rules, author_name)
        source = "heuristic"

    verdict["source"] = source

    logger.info(
        "moderation_verdict channel=%s source=%s belongs=%s confidence=%.2f suggested=%s",
        channel_name,
        source,
        verdict["belongs_to_channel"],
        verdict["confidence_score"],
        verdict["suggested_channel"],
    )
    return verdict


def should_alert(verdict):
    """True when a verdict is confident enough to be worth the handler's time."""
    return (
        not verdict["belongs_to_channel"]
        and verdict["confidence_score"] >= config.MODERATION_CONFIDENCE_THRESHOLD
    )
