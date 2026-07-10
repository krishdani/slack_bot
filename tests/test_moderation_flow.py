import unittest
from unittest.mock import patch

from slack_sdk.errors import SlackApiError

import ai
import handlers
import templates


class ModerationFlowTests(unittest.TestCase):
    def test_new_member_message_includes_rich_profile_fields(self):
        text = templates.new_member_message(
            name="Ada Lovelace",
            user_id="U123",
            joined_ts="1712345678.000200",
            workspace="Example",
            email="ada@example.com",
            title="PM",
            company="Acme",
            timezone="UTC",
            channels_joined=["announcements"],
            profile_link="https://example.slack.com/team/U123",
        )
        self.assertIn("Email", text)
        self.assertIn("Title", text)
        self.assertIn("Company", text)
        self.assertIn("Timezone", text)
        self.assertIn("Channels Joined", text)
        self.assertIn("Profile Link", text)
        self.assertIn("Join Time", text)

    def test_process_team_join_notifies_handler_for_new_member(self):
        client = object()
        with patch("store.record_member", return_value=True), patch(
            "notify.bot_user_id", return_value=None
        ), patch("notify.member_profile_data", return_value={
            "name": "Ada",
            "email": "ada@example.com",
            "title": "PM",
            "company": "Acme",
            "timezone": "UTC",
            "channels_joined": ["announcements"],
            "profile_link": "https://example.slack.com/team/U123",
        }), patch("notify.display_name_of", return_value="Ada"), patch(
            "notify.workspace_name", return_value="Example"
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_team_join(client, "U123", event_ts="1712345678.000200")

        notify_handler.assert_called_once()

    def test_process_message_event_skips_empty_message(self):
        client = object()
        with patch("moderation.evaluate") as evaluate, patch("notify.notify_handler") as notify_handler:
            handlers.process_message_event(client, {"channel": "C1", "text": "", "user": "U1"})

        evaluate.assert_not_called()
        notify_handler.assert_not_called()

    def test_process_message_event_skips_emoji_only_message(self):
        client = object()
        with patch("moderation.evaluate") as evaluate, patch("notify.notify_handler") as notify_handler:
            handlers.process_message_event(client, {"channel": "C1", "text": "😀", "user": "U1"})

        evaluate.assert_not_called()
        notify_handler.assert_not_called()

    def test_process_message_event_skips_bot_message(self):
        client = object()
        with patch("moderation.evaluate") as evaluate, patch("notify.notify_handler") as notify_handler:
            handlers.process_message_event(client, {"channel": "C1", "text": "hi", "user": "U1", "bot_id": "B1"})

        evaluate.assert_not_called()
        notify_handler.assert_not_called()

    def test_process_message_event_alerts_wrong_channel_message(self):
        client = object()
        with patch("notify.bot_user_id", return_value=None), patch("notify.channel_name_of", return_value="interview-prep"), patch(
            "notify.display_name_of", return_value="Ada"
        ), patch("notify.permalink", return_value="https://example.slack.com/"), patch(
            "notify.notify_handler", return_value=True
        ) as notify_handler, patch("moderation.evaluate", return_value={
            "belongs_to_channel": False,
            "confidence_score": 0.95,
            "explanation": "This is better suited elsewhere.",
            "suggested_channel": "#jobs",
            "suggested_reply": "Please repost elsewhere.",
            "source": "ai",
        }):
            handlers.process_message_event(client, {"channel": "C1", "channel_type": "channel", "text": "I need a job referral", "user": "U1", "ts": "1712345678.000200"})

        notify_handler.assert_called_once()

    def test_ai_moderation_accepts_requested_json_shape(self):
        class FakeCompletions:
            def create(self, **kwargs):
                return type(
                    "Resp",
                    (),
                    {
                        "choices": [
                            type(
                                "Choice",
                                (),
                                {
                                    "message": type(
                                        "Message",
                                        (),
                                        {
                                            "content": '{"correct_channel": false, "confidence": 0.94, "reason": "Different purpose", "suggested_channel": "#interview-prep", "suggested_reply": "Please repost there."}'
                                        },
                                    )()
                                },
                            )()
                        ]
                    },
                )()

        class FakeClient:
            chat = type("Chat", (), {"completions": FakeCompletions()})()

        with patch("ai._get_client", return_value=FakeClient()), patch("ai.AI_ENABLED", True):
            verdict = ai.moderate_message("Need help with interviews", "general", "Ada", {"purpose": "General"})

        self.assertIsNotNone(verdict)
        self.assertFalse(verdict["belongs_to_channel"])
        self.assertEqual(verdict["suggested_channel"], "#interview-prep")

    def test_ai_timeout_returns_none(self):
        with patch("ai._get_client", side_effect=TimeoutError("timeout")), patch("ai.AI_ENABLED", True):
            verdict = ai.moderate_message("Need help with interviews", "general", "Ada", {"purpose": "General"})

        self.assertIsNone(verdict)

    def test_process_team_join_handles_slack_api_failure(self):
        client = object()
        with patch("store.record_member", return_value=True), patch(
            "notify.bot_user_id", return_value=None
        ), patch("notify.member_profile_data", side_effect=RuntimeError("boom")), patch("notify.display_name_of", side_effect=RuntimeError("boom")), patch("notify.workspace_name", return_value="Example"), patch("notify.notify_handler", side_effect=RuntimeError("boom")):
            handlers.process_team_join(client, "U123", event_ts="1712345678.000200")


if __name__ == "__main__":
    unittest.main()
