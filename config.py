"""Central configuration for the real-time features (member alerts, moderation).

Existing modules (``ai``, ``notify``, ``store``) still read their own env vars so
that the daily report keeps working exactly as before. This module owns the
settings introduced by the real-time notification + moderation features, plus a
single shared Slack client so we don't build one per module.

Nothing here is hardcoded: every value comes from the environment, with a safe
default chosen so that a missing variable degrades quietly rather than crashing.
"""

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv()

logger = logging.getLogger("tpf-community-bot.config")


def _bool(name, default):
    """Read a boolean env var. Accepts on/true/yes/1 (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid int for %s; using default %s", name, default)
        return default


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid float for %s; using default %s", name, default)
        return default


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# The community handler (POC) who receives every DM the bot sends.
# HANDLER_SLACK_USER is the new name; HUMAN_POC_USER_ID is the name this project
# already used. They identify the same person, so we accept either and prefer
# the new one. Never hardcode a user id here.
HANDLER_SLACK_USER = (
    os.environ.get("HANDLER_SLACK_USER") or os.environ.get("HUMAN_POC_USER_ID")
)

# How many times a failed Slack write is retried before we give up and log it.
SLACK_MAX_RETRIES = _int("SLACK_MAX_RETRIES", 3)


# --------------------------------------------------------------------------- #
# Real-time member alerts (Feature 1)
# --------------------------------------------------------------------------- #

# DM the handler the moment someone joins. Turning this off does NOT affect the
# daily report — joins are still recorded and still listed there.
REALTIME_MEMBER_ALERTS = _bool("REALTIME_MEMBER_ALERTS", True)


# --------------------------------------------------------------------------- #
# Real-time channel moderation (Feature 2)
# --------------------------------------------------------------------------- #

MODERATION_ENABLED = _bool("MODERATION_ENABLED", True)

# Only alert the handler when the model is at least this sure the message does
# not belong. Raise it if the handler is getting too many alerts; lower it to
# catch more. Heuristic fallback verdicts are scored on the same scale.
MODERATION_CONFIDENCE_THRESHOLD = _float("MODERATION_CONFIDENCE_THRESHOLD", 0.7)

# Messages shorter than this are skipped ("thanks", "lol", "+1"): too little
# signal to judge, and moderating them is pure noise + wasted tokens.
MODERATION_MIN_CHARS = _int("MODERATION_MIN_CHARS", 15)

# Channels with no entry in channel_rules.py are skipped by default. Set this on
# to moderate every channel the bot can see using a generic rule.
MODERATE_UNCONFIGURED_CHANNELS = _bool("MODERATE_UNCONFIGURED_CHANNELS", False)

# Thread replies are contextual — their fit is really the parent message's fit —
# so by default only top-level messages are moderated.
MODERATE_THREAD_REPLIES = _bool("MODERATE_THREAD_REPLIES", False)

# How many times a failed OpenAI call is retried before we fall back to
# heuristics.
AI_MAX_RETRIES = _int("AI_MAX_RETRIES", 2)


# --------------------------------------------------------------------------- #
# Reply suggestions (new feature)
# --------------------------------------------------------------------------- #
# For every channel message, draft a reply the handler could send and DM it to
# them. This is INDEPENDENT of moderation: a message can produce a moderation
# alert, a reply suggestion, both, or neither. Off-topic messages already carry
# a suggested reply inside their moderation alert; this surfaces one for the
# on-topic messages too.
#
# WARNING: with the defaults below this fires on *every* message, which in an
# active workspace is a lot of DMs and a lot of OpenAI calls. Raise
# REPLY_SUGGESTIONS_MIN_CHARS, turn REPLY_SUGGESTIONS_INCLUDE_THREADS off, or
# set REPLY_SUGGESTIONS_ENABLED=off to dial it back — no redeploy of logic
# needed, just the env var.

REPLY_SUGGESTIONS_ENABLED = _bool("REPLY_SUGGESTIONS_ENABLED", True)

# Skip messages shorter than this before drafting a reply. 0 = no minimum
# (draft for everything, including "thanks" and one-word posts); 15 skips short
# noise. The env var (see render.yaml) overrides this default.
REPLY_SUGGESTIONS_MIN_CHARS = _int("REPLY_SUGGESTIONS_MIN_CHARS", 15)

# Draft replies for thread replies too, not just top-level messages.
REPLY_SUGGESTIONS_INCLUDE_THREADS = _bool("REPLY_SUGGESTIONS_INCLUDE_THREADS", True)


# --------------------------------------------------------------------------- #
# Background processing
# --------------------------------------------------------------------------- #

# Slack requires a response within 3 seconds, so AI + DM work runs off-request
# on this many worker threads.
BACKGROUND_WORKERS = _int("BACKGROUND_WORKERS", 4)


@lru_cache(maxsize=1)
def get_slack_client():
    """Return the process-wide Slack client.

    ``WebClient`` is a stateless HTTP wrapper, so it is safe to share across the
    Flask request threads and the background workers.
    """
    return WebClient(token=SLACK_BOT_TOKEN)
