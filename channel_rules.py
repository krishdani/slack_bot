"""Channel purposes and rules — the only file you edit to add a channel.

Each entry describes what a channel is *for*. Both the AI moderator (which reads
these as context) and the heuristic fallback (which reads ``redirects``) are
driven entirely by this dict, so adding a channel never means touching
application logic.

Adding a channel
----------------
Add one key, named exactly as the Slack channel (no leading ``#``)::

    "design": {
        "purpose": "Design critique and UX feedback.",
        "allowed": ["Design critique", "UX feedback", "Portfolio reviews"],
        "not_allowed": ["Job postings", "Promotions"],
        "redirects": [
            {
                "suggested_channel": "#jobs",
                "reason": "advertising a job opportunity",
                "phrases": ("we are hiring", "job opening"),
            },
        ],
    }

Fields
------
purpose       One sentence. This is the single most important field — the AI
              judges "does this belong?" against it.
allowed       Examples of content that belongs. Guidance, not an exhaustive list.
not_allowed   Examples of content that does not belong.
redirects     Used ONLY by the keyword fallback when the AI is unavailable.
              Each rule maps a set of literal lowercase phrases to a reason and
              (optionally) a better channel. ``suggested_channel`` may be None,
              meaning "flag it, but we have nowhere better to send it".
              The AI path ignores ``redirects`` entirely — it reasons from
              ``purpose``/``allowed``/``not_allowed`` instead.
"""

# A channel we have no entry for is skipped unless
# config.MODERATE_UNCONFIGURED_CHANNELS is on, in which case this stands in.
GENERIC_RULE = {
    "purpose": "General community conversation.",
    "allowed": ["Questions", "Discussions", "Community interactions"],
    "not_allowed": ["Spam", "Advertisements", "Abuse"],
    "redirects": [],
}


CHANNEL_RULES = {
    "general": {
        "purpose": "General discussions about product management and the community.",
        "allowed": [
            "Questions",
            "Discussions",
            "Product conversations",
            "Networking",
            "Community interactions",
        ],
        "not_allowed": [
            "Job postings",
            "Spam",
            "Promotions",
            "Advertisements",
        ],
        "redirects": [
            {
                "suggested_channel": "#jobs",
                "reason": "advertising a job opportunity",
                "phrases": (
                    "we are hiring", "we're hiring", "now hiring", "hiring for",
                    "job opening", "job opportunity", "open position", "open role",
                    "apply now", "send your resume", "share your cv", "dm your resume",
                ),
            },
            {
                "suggested_channel": "#events",
                "reason": "announcing an event",
                "phrases": (
                    "join our webinar", "register for the meetup", "hackathon",
                    "rsvp", "save the date",
                ),
            },
            {
                "suggested_channel": None,
                "reason": "promotional or advertising content",
                "phrases": (
                    "use code", "discount", "% off", "buy now", "limited offer",
                    "sign up now", "enroll now", "early bird", "giveaway", "coupon",
                ),
            },
        ],
    },
    "jobs": {
        "purpose": "Career opportunities and hiring.",
        "allowed": [
            "Job openings",
            "Internships",
            "Hiring posts",
            "Recruitment",
            "Candidates looking for roles",
        ],
        "not_allowed": [
            "General discussion",
            "Product questions",
            "Spam",
            "Event promotion",
        ],
        "redirects": [
            {
                "suggested_channel": "#general",
                "reason": "a general product discussion rather than a hiring post",
                "phrases": (
                    "what do you think about", "anyone using", "how do i",
                    "can someone explain", "thoughts on",
                ),
            },
        ],
    },
    "events": {
        "purpose": "Community events and meetups.",
        "allowed": [
            "Webinars",
            "Meetups",
            "Hackathons",
            "Announcements",
            "Event recaps",
        ],
        "not_allowed": [
            "Job postings",
            "Product support questions",
            "Spam",
        ],
        "redirects": [
            {
                "suggested_channel": "#jobs",
                "reason": "advertising a job opportunity",
                "phrases": (
                    "we are hiring", "we're hiring", "now hiring",
                    "job opening", "open position", "apply now",
                ),
            },
        ],
    },
}


def _normalize(channel_name):
    """Turn '#General ' / 'general' into the canonical 'general' key."""
    return (channel_name or "").strip().lstrip("#").lower()


def rules_for(channel_name):
    """Return the rule dict for a channel, or None if the channel isn't configured."""
    return CHANNEL_RULES.get(_normalize(channel_name))


def known_channels():
    """Every configured channel, '#'-prefixed — the only channels the AI may suggest."""
    return [f"#{name}" for name in CHANNEL_RULES]


def resolve_suggested_channel(suggested):
    """Validate a model-suggested channel against the config.

    Guards against hallucinated channels: anything not in ``CHANNEL_RULES``
    comes back as None, so we never tell a member to post in a channel that
    doesn't exist.
    """
    key = _normalize(suggested)
    return f"#{key}" if key in CHANNEL_RULES else None


def describe_catalog():
    """Render every channel's purpose as prompt context for the AI moderator."""
    return "\n".join(f"#{name}: {rule['purpose']}" for name, rule in CHANNEL_RULES.items())


def describe_channel(channel_name, rules):
    """Render one channel's full rule block as prompt context."""
    allowed = ", ".join(rules.get("allowed") or []) or "(unspecified)"
    not_allowed = ", ".join(rules.get("not_allowed") or []) or "(unspecified)"
    return (
        f"Channel: #{_normalize(channel_name)}\n"
        f"Purpose: {rules['purpose']}\n"
        f"Allowed: {allowed}\n"
        f"Not allowed: {not_allowed}"
    )
