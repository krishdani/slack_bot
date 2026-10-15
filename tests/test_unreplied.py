import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import store
import unreplied

KHUSHI = "U_KHUSHI"
NOW = 100_000.0


def msg(user, ts, **extra):
    return {"user": user, "ts": ts, "text": f"from {user}", **extra}


def hours_ago(h):
    return f"{NOW - h * 3600:.6f}"


class FirstUnrepliedTests(unittest.TestCase):
    def test_lone_message_from_someone_else_is_unreplied(self):
        m = msg("U1", "100.0")
        self.assertIs(unreplied.first_unreplied([m], KHUSHI), m)

    def test_khushi_replying_in_thread_clears_it(self):
        thread = [msg("U1", "100.0"), msg(KHUSHI, "200.0")]
        self.assertIsNone(unreplied.first_unreplied(thread, KHUSHI))

    def test_new_message_after_khushis_reply_is_unreplied(self):
        later = msg("U2", "300.0")
        thread = [msg("U1", "100.0"), msg(KHUSHI, "200.0"), later]
        self.assertIs(unreplied.first_unreplied(thread, KHUSHI), later)

    def test_khushis_own_post_is_never_unreplied(self):
        self.assertIsNone(unreplied.first_unreplied([msg(KHUSHI, "100.0")], KHUSHI))

    def test_bot_posts_are_ignored(self):
        thread = [msg("U1", "100.0", bot_id="B1")]
        self.assertIsNone(unreplied.first_unreplied(thread, KHUSHI))


class FindUnrepliedTests(unittest.TestCase):
    def _find(self, parents, replies=None):
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": replies or []}
        history = [
            {"channel_id": "C1", "user_id": p["user"], "text": "", "ts": p["ts"],
             "reply_count": p.get("reply_count", 0)}
            for p in parents
        ]
        with patch("collect._member_channels", return_value=["C1"]), patch(
            "collect._channel_history", return_value=history
        ), patch("config.UNREPLIED_AFTER_HOURS", 2.0), patch(
            "config.UNREPLIED_ALERT_WINDOW_HOURS", 3.0
        ):
            return unreplied.find_unreplied(client, KHUSHI, now=NOW)

    def test_only_messages_overdue_within_the_window_are_reported(self):
        found = self._find([
            msg("U_NEW", hours_ago(1)),     # still within the 2h grace
            msg("U_DUE", hours_ago(3)),     # overdue — alert
            msg("U_STALE", hours_ago(8)),   # overdue long ago — outside window
        ])
        self.assertEqual([f["user_id"] for f in found], ["U_DUE"])

    def test_thread_answered_by_khushi_is_not_reported(self):
        ts = hours_ago(3)
        found = self._find(
            [msg("U1", ts, reply_count=1)],
            replies=[msg("U1", ts), msg(KHUSHI, f"{float(ts) + 60:.6f}")],
        )
        self.assertEqual(found, [])


class RunCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db = patch("store.DB_PATH", os.path.join(self._tmp.name, "t.db"))
        self._db.start()
        store.init_db()
        self.item = {"channel_id": "C1", "ts": "1.0", "user_id": "U1",
                     "text": "hi", "is_thread_reply": False}

    def tearDown(self):
        self._db.stop()
        self._tmp.cleanup()

    def _run(self, sent_ok=True):
        with patch("config.UNREPLIED_ALERTS_ENABLED", True), patch(
            "config.MESSAGE_RELAY_USER_ID", KHUSHI
        ), patch("unreplied.find_unreplied", return_value=[self.item]), patch(
            "unreplied.alert_text", return_value="text"
        ), patch("unreplied.send_telegram", return_value=sent_ok) as send:
            result = unreplied.run_check(object())
        return result, send

    def test_each_message_is_alerted_only_once(self):
        first, send1 = self._run()
        second, send2 = self._run()
        self.assertEqual(first["sent"], 1)
        send1.assert_called_once()
        send2.assert_not_called()
        self.assertEqual(second["found"], 0)

    def test_failed_send_is_retried_next_check(self):
        self._run(sent_ok=False)
        _, send = self._run()
        send.assert_called_once()

    def test_skips_when_not_configured(self):
        with patch("config.UNREPLIED_ALERTS_ENABLED", False), patch(
            "unreplied.find_unreplied"
        ) as find:
            result = unreplied.run_check(object())
        self.assertEqual(result, {"skipped": "not_configured"})
        find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
