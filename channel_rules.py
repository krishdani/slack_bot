"""Channel purposes and rules — the only file you edit to add a channel.

Each entry describes what a channel is *for*. Both the AI moderator (which reads
these as context) and the heuristic fallback (which reads ``redirects``) are
driven entirely by this dict, so adding a channel never means touching
application logic.
"""

# A channel we have no entry for is skipped unless
# config.MODERATE_UNCONFIGURED_CHANNELS is on, in which case this stands in.
GENERIC_RULE = {
    "purpose": "General community conversation.",
    "allowed_topics": ["Questions", "Discussions", "Community interactions"],
    "disallowed_topics": ["Spam", "Advertisements", "Abuse"],
    "examples": ["General product discussion", "Community updates"],
    "allowed": ["Questions", "Discussions", "Community interactions"],
    "not_allowed": ["Spam", "Advertisements", "Abuse"],
    "redirects": [],
}


CHANNEL_RULES = {
    "announcements": {
        "purpose": "Official announcements, launches and important community updates.",
        "allowed_topics": [
            "Official announcements",
            "Launches",
            "Events",
            "Community updates",
        ],
        "disallowed_topics": [
            "Random discussion",
            "Interview questions",
            "Resume review",
            "Debugging",
            "Job hiring questions",
        ],
        "examples": [
            "Product launch updates",
            "Community deadlines",
            "Platform announcements",
        ],
        "allowed": ["Official announcements", "Launches", "Events", "Community updates"],
        "not_allowed": ["Random discussion", "Interview questions", "Resume review"],
        "redirects": [],
    },
    "ask-for-help": {
        "purpose": "Questions, troubleshooting and requests for guidance.",
        "allowed_topics": [
            "Asking questions",
            "Seeking guidance",
            "Troubleshooting",
            "Technical help",
        ],
        "disallowed_topics": [
            "Promotions",
            "Product launches",
            "Random chatter",
        ],
        "examples": ["How do I debug this?", "Can someone help with setup?"],
        "allowed": ["Asking questions", "Seeking guidance", "Troubleshooting"],
        "not_allowed": ["Promotions", "Product launches", "Random chatter"],
        "redirects": [],
    },
    "experience-a-week-in-women-in-product": {
        "purpose": "Stories and reflections about the women in product experience.",
        "allowed_topics": ["Personal stories", "Community experiences", "Learnings"],
        "disallowed_topics": ["Promotions", "Jobs", "Random memes"],
        "examples": ["Episode reflections", "Member takeaways"],
        "allowed": ["Personal stories", "Community experiences", "Learnings"],
        "not_allowed": ["Promotions", "Jobs", "Random memes"],
        "redirects": [],
    },
    "fintech": {
        "purpose": "Fintech-related discussion and updates.",
        "allowed_topics": ["Fintech discussions", "Payments", "Banking product ideas"],
        "disallowed_topics": ["Recruiting", "Promotion", "Unrelated memes"],
        "examples": ["Payments product discussion", "Fintech case studies"],
        "allowed": ["Fintech discussions", "Payments", "Banking product ideas"],
        "not_allowed": ["Recruiting", "Promotion", "Unrelated memes"],
        "redirects": [],
    },
    "general": {
        "purpose": "General discussions about product management and the community.",
        "allowed_topics": [
            "Questions",
            "Discussions",
            "Product conversations",
            "Networking",
            "Community interactions",
        ],
        "disallowed_topics": ["Job postings", "Spam", "Promotions", "Advertisements"],
        "examples": ["General PM discussion", "Community networking"],
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
                "suggested_channel": "#jobs-gigs-hiring-threads",
                "reason": "advertising a job opportunity",
                "phrases": (
                    "we are hiring", "we're hiring", "now hiring", "hiring for",
                    "job opening", "job opportunity", "open position", "open role",
                    "apply now", "send your resume", "share your cv", "dm your resume",
                ),
            },
            {
                "suggested_channel": "#announcements",
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
    "genai-rush-announcements": {
        "purpose": "Announcements and updates related to GenAI Rush.",
        "allowed_topics": ["GenAI updates", "Announcements", "Community news"],
        "disallowed_topics": ["Recruiting", "Unrelated product debate"],
        "examples": ["GenAI event updates", "Announcement recaps"],
        "allowed": ["GenAI updates", "Announcements", "Community news"],
        "not_allowed": ["Recruiting", "Unrelated product debate"],
        "redirects": [],
    },
    "grabchai-meetups": {
        "purpose": "Meetups, chai and community social gatherings.",
        "allowed_topics": ["Meetups", "Social gatherings", "Community hangouts"],
        "disallowed_topics": ["Hiring", "Promotions", "Work support requests"],
        "examples": ["Meetup reminders", "Community hangout invites"],
        "allowed": ["Meetups", "Social gatherings", "Community hangouts"],
        "not_allowed": ["Hiring", "Promotions", "Work support requests"],
        "redirects": [],
    },
    "interview-prep": {
        "purpose": "Interview preparation, resumes, mock interviews and salary conversations.",
        "allowed_topics": [
            "Interview questions",
            "Resume review",
            "Mock interviews",
            "Salary negotiation",
            "Interview tips",
        ],
        "disallowed_topics": ["Promotions", "Launches", "Product discussion"],
        "examples": ["Mock interview practice", "Resume feedback"],
        "allowed": [
            "Interview questions",
            "Resume review",
            "Mock interviews",
            "Salary negotiation",
            "Interview tips",
        ],
        "not_allowed": ["Promotions", "Launches", "Product discussion"],
        "redirects": [],
    },
    "jobs-gigs-hiring-threads": {
        "purpose": "Hiring, referrals, internships and job openings.",
        "allowed_topics": ["Hiring", "Referrals", "Internships", "Job openings"],
        "disallowed_topics": ["Feature requests", "Memes", "Promotions"],
        "examples": ["Open roles", "Referral requests"],
        "allowed": ["Hiring", "Referrals", "Internships", "Job openings"],
        "not_allowed": ["Feature requests", "Memes", "Promotions"],
        "redirects": [],
    },
    "product-analytics-101-announcements": {
        "purpose": "Announcements for analytics learning content and updates.",
        "allowed_topics": ["Analytics announcements", "Learning updates"],
        "disallowed_topics": ["Off-topic discussion", "Hiring posts"],
        "examples": ["Analytics course launch", "Session reminders"],
        "allowed": ["Analytics announcements", "Learning updates"],
        "not_allowed": ["Off-topic discussion", "Hiring posts"],
        "redirects": [],
    },
    "product-decks": {
        "purpose": "Product deck reviews and presentation feedback.",
        "allowed_topics": ["Deck critique", "Presentation feedback", "Design review"],
        "disallowed_topics": ["Job postings", "Random memes"],
        "examples": ["Slide feedback", "Deck walkthrough"],
        "allowed": ["Deck critique", "Presentation feedback", "Design review"],
        "not_allowed": ["Job postings", "Random memes"],
        "redirects": [],
    },
    "product-discussions": {
        "purpose": "Product strategy, PM discussion, metrics and prioritization.",
        "allowed_topics": ["Product strategy", "PM discussion", "Metrics", "UX", "Prioritization"],
        "disallowed_topics": ["Promotions", "Interview prep", "Random chatter"],
        "examples": ["Metrics trade-offs", "Feature prioritization"],
        "allowed": ["Product strategy", "PM discussion", "Metrics", "UX", "Prioritization"],
        "not_allowed": ["Promotions", "Interview prep", "Random chatter"],
        "redirects": [],
    },
    "product-led-growth-announcements": {
        "purpose": "PLG announcements and related product growth updates.",
        "allowed_topics": ["PLG announcements", "Growth updates", "Launches"],
        "disallowed_topics": ["Customer support", "Hiring posts"],
        "examples": ["Growth experiment launch", "PLG update"],
        "allowed": ["PLG announcements", "Growth updates", "Launches"],
        "not_allowed": ["Customer support", "Hiring posts"],
        "redirects": [],
    },
    "product-teardown": {
        "purpose": "Screenshots, product review and feature breakdowns.",
        "allowed_topics": ["Screenshots", "Product review", "Feature breakdown", "Teardown"],
        "disallowed_topics": ["Interview prep", "Job promos", "General chat"],
        "examples": ["Feature teardown", "Product review screenshot"],
        "allowed": ["Screenshots", "Product review", "Feature breakdown", "Teardown"],
        "not_allowed": ["Interview prep", "Job promos", "General chat"],
        "redirects": [],
    },
    "promo-anything-you-want": {
        "purpose": "Promotions, events and community advocacy.",
        "allowed_topics": [
            "Promotions",
            "Startup launches",
            "Webinars",
            "Newsletters",
            "Product launch",
            "Events",
            "Community promotion",
        ],
        "disallowed_topics": [
            "Interview questions",
            "Resume review",
            "Debugging",
            "Random discussion",
            "Hiring questions",
        ],
        "examples": ["Startup launch announcement", "Community event promo"],
        "allowed": [
            "Promotions",
            "Startup launches",
            "Webinars",
            "Newsletters",
            "Product launch",
            "Events",
            "Community promotion",
        ],
        "not_allowed": [
            "Interview questions",
            "Resume review",
            "Debugging",
            "Random discussion",
            "Hiring questions",
        ],
        "redirects": [],
    },
    "tpf-reading-club": {
        "purpose": "Reading club discussions and book recaps.",
        "allowed_topics": ["Book discussions", "Reading club", "Recaps"],
        "disallowed_topics": ["Job openings", "Product launches"],
        "examples": ["Book recap", "Chapter discussion"],
        "allowed": ["Book discussions", "Reading club", "Recaps"],
        "not_allowed": ["Job openings", "Product launches"],
        "redirects": [],
    },
    "vibesprint": {
        "purpose": "Community vibes, social moments and casual share-outs.",
        "allowed_topics": ["Vibes", "Community moments", "Casual shares"],
        "disallowed_topics": ["Recruitment", "Technical help"],
        "examples": ["Community wins", "Casual check-ins"],
        "allowed": ["Vibes", "Community moments", "Casual shares"],
        "not_allowed": ["Recruitment", "Technical help"],
        "redirects": [],
    },
    "virtual-hangout": {
        "purpose": "Community social hangouts and informal conversations.",
        "allowed_topics": ["Social hangout", "Casual conversation", "Community vibes"],
        "disallowed_topics": ["Promotions", "Interview prep", "Support requests"],
        "examples": ["Hangout reminders", "Casual check-ins"],
        "allowed": ["Social hangout", "Casual conversation", "Community vibes"],
        "not_allowed": ["Promotions", "Interview prep", "Support requests"],
        "redirects": [],
    },
    "weekly-product-ama": {
        "purpose": "Weekly product AMA discussions and questions.",
        "allowed_topics": ["AMA questions", "Community Q&A", "Product discussion"],
        "disallowed_topics": ["Promotions", "Recruiting", "Off-topic memes"],
        "examples": ["AMA Q&A", "Weekly product questions"],
        "allowed": ["AMA questions", "Community Q&A", "Product discussion"],
        "not_allowed": ["Promotions", "Recruiting", "Off-topic memes"],
        "redirects": [],
    },
    "welcome-to-the-club": {
        "purpose": "New member welcome posts and introductions.",
        "allowed_topics": ["Introductions", "Welcome posts", "Member intros"],
        "disallowed_topics": ["Promotions", "Hiring posts", "General support"],
        "examples": ["Welcome message", "Intro thread"],
        "allowed": ["Introductions", "Welcome posts", "Member intros"],
        "not_allowed": ["Promotions", "Hiring posts", "General support"],
        "redirects": [],
    },
    "jobs": {
        "purpose": "Career opportunities and hiring.",
        "allowed_topics": ["Job openings", "Internships", "Hiring posts", "Recruitment"],
        "disallowed_topics": ["General discussion", "Product questions", "Spam", "Event promotion"],
        "examples": ["Open roles", "Recruitment posts"],
        "allowed": ["Job openings", "Internships", "Hiring posts", "Recruitment"],
        "not_allowed": ["General discussion", "Product questions", "Spam", "Event promotion"],
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
        "allowed_topics": ["Webinars", "Meetups", "Hackathons", "Announcements", "Event recaps"],
        "disallowed_topics": ["Job postings", "Product support questions", "Spam"],
        "examples": ["Community meetup", "Hackathon announcement"],
        "allowed": ["Webinars", "Meetups", "Hackathons", "Announcements", "Event recaps"],
        "not_allowed": ["Job postings", "Product support questions", "Spam"],
        "redirects": [
            {
                "suggested_channel": "#jobs-gigs-hiring-threads",
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
    allowed = ", ".join(rules.get("allowed_topics") or rules.get("allowed") or []) or "(unspecified)"
    not_allowed = ", ".join(rules.get("disallowed_topics") or rules.get("not_allowed") or []) or "(unspecified)"
    examples = ", ".join(rules.get("examples") or []) or "(none provided)"
    return (
        f"Channel: #{_normalize(channel_name)}\n"
        f"Purpose: {rules['purpose']}\n"
        f"Allowed: {allowed}\n"
        f"Not allowed: {not_allowed}\n"
        f"Examples: {examples}"
    )
