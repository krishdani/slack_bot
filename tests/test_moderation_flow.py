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

    # --- Welcome DM (the new-member button) ---------------------------------

    def test_welcome_dm_message_uses_first_name_and_fixed_body(self):
        text = templates.welcome_dm_message("Ram Kumar")
        self.assertTrue(text.startswith("Hey Ram!"))
        self.assertIn("Welcome to The Product Folks", text)
        self.assertIn("https://www.theproductfolks.com/grabchai", text)
        self.assertIn("#welcome-to-the-club", text)

    def test_welcome_dm_message_falls_back_when_no_name(self):
        self.assertTrue(templates.welcome_dm_message("").startswith("Hey there!"))
        self.assertTrue(templates.welcome_dm_message(None).startswith("Hey there!"))

    def test_new_member_blocks_carry_a_send_button_with_joiner(self):
        blocks = templates.new_member_blocks(
            "🎉 New Member Joined", "body text", "U123", "Ram"
        )
        button = blocks[-1]["elements"][0]
        self.assertEqual(button["action_id"], templates.SEND_WELCOME_DM_ACTION)
        import json as _json
        value = _json.loads(button["value"])
        self.assertEqual(value, {"user_id": "U123", "name": "Ram"})

    def test_team_join_alert_includes_welcome_button_when_enabled(self):
        client = object()
        with patch("store.record_member", return_value=True), patch(
            "notify.bot_user_id", return_value=None
        ), patch("notify.member_profile_data", return_value={"name": "Ram"}), patch(
            "notify.display_name_of", return_value="Ram"
        ), patch("notify.workspace_name", return_value="Example"), patch(
            "config.WELCOME_DM_ENABLED", True
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_team_join(client, "U123", event_ts="1712345678.000200")

        blocks = notify_handler.call_args.kwargs["blocks"]
        self.assertIsNotNone(blocks)
        self.assertEqual(
            blocks[-1]["elements"][0]["action_id"], templates.SEND_WELCOME_DM_ACTION
        )

    def test_team_join_alert_has_no_button_when_disabled(self):
        client = object()
        with patch("store.record_member", return_value=True), patch(
            "notify.bot_user_id", return_value=None
        ), patch("notify.member_profile_data", return_value={"name": "Ram"}), patch(
            "notify.display_name_of", return_value="Ram"
        ), patch("notify.workspace_name", return_value="Example"), patch(
            "config.WELCOME_DM_ENABLED", False
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_team_join(client, "U123", event_ts="1712345678.000200")

        self.assertIsNone(notify_handler.call_args.kwargs["blocks"])

    def test_process_welcome_dm_sends_fixed_message_to_joiner(self):
        client = object()
        with patch("notify.dm_user", return_value=True) as dm_user, patch(
            "notify.display_name_of", return_value="Ram"
        ):
            handlers.process_welcome_dm(client, "U123", "Ram")

        dm_user.assert_called_once()
        sent_text = dm_user.call_args.args[2]
        self.assertTrue(sent_text.startswith("Hey Ram!"))

    def test_process_welcome_dm_sends_as_handler_when_user_token_set(self):
        bot, as_user = object(), object()
        with patch("notify.dm_user", return_value=True) as dm_user, patch(
            "config.get_handler_user_client", return_value=as_user
        ), patch("notify.display_name_of", return_value="Ram"):
            handlers.process_welcome_dm(bot, "U123", "Ram")

        dm_user.assert_called_once()
        # The DM must go out on the user-token client, not the bot client.
        self.assertIs(dm_user.call_args.args[0], as_user)

    def test_process_welcome_dm_falls_back_to_bot_when_user_token_fails(self):
        bot, as_user = object(), object()
        with patch("notify.dm_user", side_effect=[False, True]) as dm_user, patch(
            "config.get_handler_user_client", return_value=as_user
        ), patch("notify.display_name_of", return_value="Ram"):
            handlers.process_welcome_dm(bot, "U123", "Ram")

        self.assertEqual(dm_user.call_count, 2)
        self.assertIs(dm_user.call_args_list[0].args[0], as_user)
        self.assertIs(dm_user.call_args_list[1].args[0], bot)

    def test_process_welcome_dm_uses_bot_when_no_user_token(self):
        bot = object()
        with patch("notify.dm_user", return_value=True) as dm_user, patch(
            "config.get_handler_user_client", return_value=None
        ), patch("notify.display_name_of", return_value="Ram"):
            handlers.process_welcome_dm(bot, "U123", "Ram")

        dm_user.assert_called_once()
        self.assertIs(dm_user.call_args.args[0], bot)

    def test_process_welcome_dm_noops_without_joiner(self):
        with patch("notify.dm_user") as dm_user:
            handlers.process_welcome_dm(object(), None, "Ram")
        dm_user.assert_not_called()

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

    # --- Reply suggestions --------------------------------------------------

    def test_reply_suggestion_dms_handler_with_draft(self):
        client = object()
        with patch("notify.bot_user_id", return_value=None), patch(
            "notify.channel_name_of", return_value="product-discussions"
        ), patch("notify.display_name_of", return_value="Ada"), patch(
            "notify.permalink", return_value="https://example.slack.com/"
        ), patch("channel_rules.rules_for", return_value={"purpose": "PM talk"}), patch(
            "ai.suggest_reply", return_value="Hi Ada, great question — here's a pointer."
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_reply_suggestion(
                client,
                {"channel": "C1", "channel_type": "channel", "text": "How do I run an experiment?", "user": "U1", "ts": "1712345678.000200"},
            )

        notify_handler.assert_called_once()
        self.assertEqual(notify_handler.call_args.kwargs["title"], "💬 Suggested Reply")

    def test_reply_suggestion_skips_bot_message(self):
        client = object()
        with patch("ai.suggest_reply") as suggest, patch("notify.notify_handler") as notify_handler:
            handlers.process_reply_suggestion(
                client,
                {"channel": "C1", "channel_type": "channel", "text": "hello there", "user": "U1", "bot_id": "B1"},
            )

        suggest.assert_not_called()
        notify_handler.assert_not_called()

    def test_reply_suggestion_no_dm_when_ai_returns_none(self):
        client = object()
        with patch("notify.bot_user_id", return_value=None), patch(
            "notify.channel_name_of", return_value="product-discussions"
        ), patch("notify.display_name_of", return_value="Ada"), patch(
            "channel_rules.rules_for", return_value=None
        ), patch("ai.suggest_reply", return_value=None), patch(
            "notify.notify_handler"
        ) as notify_handler:
            handlers.process_reply_suggestion(
                client,
                {"channel": "C1", "channel_type": "channel", "text": "How do I run an experiment?", "user": "U1", "ts": "1712345678.000200"},
            )

        notify_handler.assert_not_called()

    def test_reply_suggestion_disabled_skips_everything(self):
        client = object()
        with patch("config.REPLY_SUGGESTIONS_ENABLED", False), patch(
            "ai.suggest_reply"
        ) as suggest, patch("notify.notify_handler") as notify_handler:
            handlers.process_reply_suggestion(
                client,
                {"channel": "C1", "channel_type": "channel", "text": "How do I run an experiment?", "user": "U1", "ts": "1712345678.000200"},
            )

        suggest.assert_not_called()
        notify_handler.assert_not_called()

    def test_reply_suggestion_template_shows_draft_and_disclaimer(self):
        text = templates.reply_suggestion(
            channel_name="product-discussions",
            author_name="Ada",
            author_id="U1",
            timestamp="1712345678.000200",
            text="How do I run an experiment?",
            suggested_reply="Hi Ada, here's how.",
            permalink="https://example.slack.com/",
        )
        self.assertIn("Suggested Reply", text)
        self.assertIn("Hi Ada, here's how.", text)
        self.assertIn("nothing was posted", text)


    # --- Message relay ------------------------------------------------------

    def _relay_event(self, **overrides):
        event = {
            "channel": "C1",
            "channel_type": "channel",
            "text": "Has anyone used Amplitude for retention analysis?",
            "user": "U1",
            "ts": "1712345678.000200",
        }
        event.update(overrides)
        return event

    def _relay_patches(self):
        """The Slack lookups process_message_relay makes, all stubbed."""
        return (
            patch("notify.bot_user_id", return_value=None),
            patch("notify.channel_name_of", return_value="product-analytics-101"),
            patch("notify.display_name_of", return_value="Ada"),
            patch("notify.permalink", return_value="https://example.slack.com/"),
        )

    def test_message_relay_dms_handler_for_an_ordinary_message(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_message_relay(client, self._relay_event())

        notify_handler.assert_called_once()
        self.assertEqual(notify_handler.call_args.kwargs["title"], "📨 New Message")
        body = notify_handler.call_args.kwargs["message"]
        self.assertIn("#product-analytics-101", body)
        self.assertIn("<@U1>", body)
        self.assertIn("Amplitude", body)

    def test_message_relay_sends_for_noise_the_other_features_skip(self):
        # "thanks" is dropped by moderation and reply suggestions. The relay's
        # whole purpose is that it isn't — every message means every message.
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("config.MESSAGE_RELAY_MIN_CHARS", 0), patch(
            "notify.notify_handler", return_value=True
        ) as notify_handler:
            handlers.process_message_relay(client, self._relay_event(text="thanks"))

        notify_handler.assert_called_once()

    def test_message_relay_uses_no_ai(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("notify.notify_handler", return_value=True), patch(
            "ai.suggest_reply"
        ) as suggest, patch("moderation.evaluate") as evaluate:
            handlers.process_message_relay(client, self._relay_event())

        suggest.assert_not_called()
        evaluate.assert_not_called()

    def test_message_relay_marks_thread_replies(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("config.MESSAGE_RELAY_INCLUDE_THREADS", True), patch(
            "notify.notify_handler", return_value=True
        ) as notify_handler:
            handlers.process_message_relay(
                client, self._relay_event(thread_ts="1712345600.000100")
            )

        self.assertIn("thread reply", notify_handler.call_args.kwargs["message"])

    def test_message_relay_skips_thread_replies_when_configured_off(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("config.MESSAGE_RELAY_INCLUDE_THREADS", False), patch(
            "notify.notify_handler"
        ) as notify_handler:
            handlers.process_message_relay(
                client, self._relay_event(thread_ts="1712345600.000100")
            )

        notify_handler.assert_not_called()

    def test_message_relay_skips_bot_posts_by_default(self):
        client = object()
        with patch("config.MESSAGE_RELAY_ENABLED", True), patch(
            "config.MESSAGE_RELAY_INCLUDE_BOTS", False
        ), patch("notify.notify_handler") as notify_handler:
            handlers.process_message_relay(client, self._relay_event(bot_id="B1"))

        notify_handler.assert_not_called()

    def test_message_relay_skips_edits_and_joins(self):
        client = object()
        with patch("config.MESSAGE_RELAY_ENABLED", True), patch(
            "notify.notify_handler"
        ) as notify_handler:
            for subtype in ("message_changed", "message_deleted", "channel_join"):
                handlers.process_message_relay(
                    client, self._relay_event(subtype=subtype)
                )

        notify_handler.assert_not_called()

    def test_message_relay_relays_a_file_share(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("notify.notify_handler", return_value=True) as notify_handler:
            handlers.process_message_relay(
                client, self._relay_event(subtype="file_share")
            )

        notify_handler.assert_called_once()

    def test_message_relay_skips_dms_to_the_bot(self):
        client = object()
        with patch("config.MESSAGE_RELAY_ENABLED", True), patch(
            "notify.notify_handler"
        ) as notify_handler:
            handlers.process_message_relay(client, self._relay_event(channel_type="im"))

        notify_handler.assert_not_called()

    def test_message_relay_skips_the_bots_own_messages(self):
        client = object()
        with patch("config.MESSAGE_RELAY_ENABLED", True), patch(
            "notify.bot_user_id", return_value="U_BOT"
        ), patch("notify.notify_handler") as notify_handler:
            handlers.process_message_relay(client, self._relay_event(user="U_BOT"))

        notify_handler.assert_not_called()

    def test_message_relay_disabled_skips_everything(self):
        client = object()
        with patch("config.MESSAGE_RELAY_ENABLED", False), patch(
            "notify.notify_handler"
        ) as notify_handler:
            handlers.process_message_relay(client, self._relay_event())

        notify_handler.assert_not_called()

    def test_message_relay_survives_a_failed_dm(self):
        client = object()
        bot_id, channel, name, link = self._relay_patches()
        with bot_id, channel, name, link, patch(
            "config.MESSAGE_RELAY_ENABLED", True
        ), patch("notify.notify_handler", side_effect=RuntimeError("boom")):
            handlers.process_message_relay(client, self._relay_event())  # must not raise

    def test_message_relay_template_has_no_assessment_or_draft(self):
        text = templates.message_relay(
            channel_name="product-decks",
            author_name="Ada",
            author_id="U1",
            timestamp="1712345678.000200",
            text="Sharing my teardown deck.",
            permalink="https://example.slack.com/",
        )
        self.assertIn("#product-decks", text)
        self.assertIn("Sharing my teardown deck.", text)
        self.assertIn("View message in Slack", text)
        self.assertNotIn("Suggested Reply", text)
        self.assertNotIn("AI Assessment", text)

    # --- Two-bot split (original bot vs reply bot) --------------------------

    def test_primary_bot_runs_join_and_moderation_not_reply(self):
        caps = {handlers.CAP_JOIN, handlers.CAP_MODERATION}
        # A join event: handled.
        with patch("background.submit") as submit:
            self.assertEqual(
                handlers.dispatch(object(), {"type": "team_join", "user": "U1"}, caps),
                "process_team_join",
            )
            submit.assert_called_once()
        # A message: moderation runs, reply-suggestion does NOT.
        with patch("background.submit") as submit:
            result = handlers.dispatch(
                object(),
                {"type": "message", "channel": "C1", "text": "hi there", "user": "U1"},
                caps,
            )
        self.assertEqual(result, "process_message_event")
        submit.assert_called_once()

    def test_reply_bot_runs_only_reply_suggestion(self):
        caps = {handlers.CAP_REPLY}
        # A message: only reply-suggestion runs, moderation does NOT.
        with patch("background.submit") as submit:
            result = handlers.dispatch(
                object(),
                {"type": "message", "channel": "C1", "text": "hi there", "user": "U1"},
                caps,
            )
        self.assertEqual(result, "process_reply_suggestion")
        submit.assert_called_once()
        # A join event on the reply bot: ignored.
        with patch("background.submit") as submit:
            self.assertIsNone(
                handlers.dispatch(object(), {"type": "team_join", "user": "U1"}, caps)
            )
            submit.assert_not_called()

    def test_relay_bot_runs_only_the_message_relay(self):
        caps = {handlers.CAP_RELAY}
        with patch("background.submit") as submit:
            result = handlers.dispatch(
                object(),
                {"type": "message", "channel": "C1", "text": "hi there", "user": "U1"},
                caps,
            )
        self.assertEqual(result, "process_message_relay")
        submit.assert_called_once()
        # A join event on the relay bot: ignored.
        with patch("background.submit") as submit:
            self.assertIsNone(
                handlers.dispatch(object(), {"type": "team_join", "user": "U1"}, caps)
            )
            submit.assert_not_called()

    def test_primary_bot_does_not_relay_when_the_relay_bot_owns_it(self):
        caps = {handlers.CAP_JOIN, handlers.CAP_MODERATION, handlers.CAP_REPLY}
        with patch("background.submit") as submit:
            result = handlers.dispatch(
                object(),
                {"type": "message", "channel": "C1", "text": "hi there", "user": "U1"},
                caps,
            )
        self.assertNotIn("process_message_relay", result)
        self.assertEqual(submit.call_count, 2)

    def test_single_bot_mode_runs_everything(self):
        with patch("background.submit") as submit:
            result = handlers.dispatch(
                object(),
                {"type": "message", "channel": "C1", "text": "hi there", "user": "U1"},
            )
        self.assertEqual(
            result,
            "process_message_event,process_reply_suggestion,process_message_relay",
        )
        self.assertEqual(submit.call_count, 3)

    def test_bot_user_id_is_cached_per_client(self):
        import notify

        class FakeClient:
            def __init__(self, token, uid):
                self.token = token
                self._uid = uid

            def auth_test(self):
                return {"user_id": self._uid}

        notify._bot_user_ids.clear()
        msg_bot = FakeClient("xoxb-message", "U_MSG")
        join_bot = FakeClient("xoxb-join", "U_JOIN")
        # Two different bots must resolve to two different ids, not share one.
        self.assertEqual(notify.bot_user_id(msg_bot), "U_MSG")
        self.assertEqual(notify.bot_user_id(join_bot), "U_JOIN")
        self.assertEqual(notify.bot_user_id(msg_bot), "U_MSG")


if __name__ == "__main__":
    unittest.main()
