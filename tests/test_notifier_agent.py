import unittest
from unittest.mock import patch

from codex_speed.notifier_agent import (
    AttentionAgent,
    MacOSNotifier,
    session_is_inactive,
    text_needs_paused_attention,
    text_needs_permission_attention,
)


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, title: str, message: str) -> None:
        self.notifications.append((title, message))


class NotifierAgentTests(unittest.TestCase):
    def test_detects_permission_prompt_text(self) -> None:
        self.assertTrue(text_needs_permission_attention("Do you want to allow this command?"))
        self.assertTrue(text_needs_permission_attention("This operation requires approval."))
        self.assertTrue(text_needs_permission_attention("需要确认权限后继续"))
        self.assertFalse(text_needs_permission_attention("permission denied while connecting"))

    def test_detects_paused_prompt_text(self) -> None:
        self.assertTrue(text_needs_paused_attention("Session paused - waiting for user input."))
        self.assertTrue(text_needs_paused_attention("Press enter to continue"))
        self.assertTrue(text_needs_paused_attention("暂停，等待输入"))
        self.assertFalse(text_needs_paused_attention("approval required"))

    def test_session_inactivity_requires_active_output_seen_session(self) -> None:
        self.assertTrue(
            session_is_inactive(last_activity_at=100.0, now=160.0, pause_seconds=60.0)
        )
        self.assertFalse(
            session_is_inactive(last_activity_at=100.0, now=159.0, pause_seconds=60.0)
        )
        self.assertFalse(
            session_is_inactive(
                last_activity_at=100.0,
                now=200.0,
                pause_seconds=60.0,
                active=False,
            )
        )
        self.assertFalse(
            session_is_inactive(
                last_activity_at=100.0,
                now=200.0,
                pause_seconds=60.0,
                output_seen=False,
            )
        )

    def test_agent_notifies_for_permission_prompt_output(self) -> None:
        clock = FakeClock(10.0)
        notifier = RecordingNotifier()
        agent = AttentionAgent(notifier=notifier, clock=clock)
        agent.start_session("session-1", "tui")

        agent.observe_output("session-1", b"Do you want to allow this command?")

        self.assertEqual(notifier.notifications[0][0], "Codex Needs Attention")
        self.assertIn("session-1"[:8], notifier.notifications[0][1])

    def test_agent_notifies_for_paused_output(self) -> None:
        clock = FakeClock(20.0)
        notifier = RecordingNotifier()
        agent = AttentionAgent(notifier=notifier, clock=clock)
        agent.start_session("session-2", "tui")

        agent.observe_output("session-2", b"Session paused - waiting for user input.")

        self.assertEqual(notifier.notifications[0][0], "Codex Is Paused")

    def test_agent_notifies_for_idle_session_once_per_dedupe_window(self) -> None:
        clock = FakeClock(0.0)
        notifier = RecordingNotifier()
        agent = AttentionAgent(
            notifier=notifier,
            clock=clock,
            pause_seconds=30.0,
            dedupe_seconds=60.0,
        )
        agent.start_session("session-3", "exec")
        agent.observe_output("session-3", b"working")

        clock.now = 30.0
        agent.check_idle()
        clock.now = 40.0
        agent.check_idle()
        clock.now = 91.0
        agent.check_idle()

        self.assertEqual(
            [title for title, _message in notifier.notifications],
            ["Codex May Be Waiting", "Codex May Be Waiting"],
        )

    def test_agent_suppresses_duplicate_permission_notifications(self) -> None:
        clock = FakeClock(100.0)
        notifier = RecordingNotifier()
        agent = AttentionAgent(
            notifier=notifier,
            clock=clock,
            pause_seconds=30.0,
            dedupe_seconds=60.0,
        )
        agent.start_session("session-4", "tui")

        agent.observe_output("session-4", b"Do you want to allow this command?")
        clock.now = 120.0
        agent.observe_output("session-4", b"Do you want to allow this command?")

        self.assertEqual(len(notifier.notifications), 1)

    def test_macos_notifier_falls_back_when_osascript_fails(self) -> None:
        fallback = RecordingNotifier()
        notifier = MacOSNotifier(fallback=fallback)

        with patch("codex_speed.notifier_agent.subprocess.run", side_effect=OSError):
            notifier.notify("Title", "Message")

        self.assertEqual(fallback.notifications, [("Title", "Message")])


if __name__ == "__main__":
    unittest.main()
