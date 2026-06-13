import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_speed.session_focus import (
    SessionRegistry,
    SessionTarget,
    build_focus_command,
    focus_session,
    load_session_target,
    safe_session_id,
    terminal_app_from_program,
    write_session_target,
)


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class SessionFocusTests(unittest.TestCase):
    def test_terminal_app_from_program_maps_common_macos_terminals(self) -> None:
        self.assertEqual(terminal_app_from_program("Apple_Terminal"), "Terminal")
        self.assertEqual(terminal_app_from_program("iTerm.app"), "iTerm2")
        self.assertEqual(terminal_app_from_program("WezTerm.app"), "WezTerm")
        self.assertIsNone(terminal_app_from_program(None))

    def test_registry_writes_and_marks_session_target_ended(self) -> None:
        with TemporaryDirectory() as temp_dir:
            clock = FakeClock(10.0)
            registry = SessionRegistry(state_dir=Path(temp_dir), clock=clock)
            with (
                patch("codex_speed.session_focus.current_tty", return_value="/dev/ttys001"),
                patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}),
            ):
                registry.start_session("session-1", "tui")

            target = load_session_target("session-1", state_dir=Path(temp_dir))
            self.assertIsNotNone(target)
            assert target is not None
            self.assertEqual(target.tty, "/dev/ttys001")
            self.assertEqual(target.terminal_app, "iTerm2")
            self.assertIsNone(target.ended_at)

            clock.now = 20.0
            registry.end_session("session-1")

            ended = load_session_target("session-1", state_dir=Path(temp_dir))
            self.assertIsNotNone(ended)
            assert ended is not None
            self.assertEqual(ended.ended_at, 20.0)

    def test_safe_session_id_rejects_shell_metacharacters(self) -> None:
        self.assertEqual(safe_session_id("abc-123_DEF.4"), "abc-123_DEF.4")
        with self.assertRaises(ValueError):
            safe_session_id("abc;rm -rf")

    def test_build_focus_command_targets_focus_session_cli(self) -> None:
        command = build_focus_command(
            "session-1",
            python_bin="/usr/bin/python3",
            source_root=Path("/tmp/codex src"),
        )

        self.assertIn("PYTHONPATH='/tmp/codex src'", command)
        self.assertIn("/usr/bin/python3 -m codex_speed focus-session --quiet session-1", command)

    def test_focus_session_finds_terminal_tty(self) -> None:
        with TemporaryDirectory() as temp_dir:
            write_session_target(
                SessionTarget(
                    session="session-1",
                    mode="tui",
                    tty="/dev/ttys001",
                    terminal_program="Apple_Terminal",
                    terminal_app="Terminal",
                    pid=123,
                    started_at=1.0,
                ),
                state_dir=Path(temp_dir),
            )
            scripts: list[str] = []

            def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                scripts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout="focused\n", stderr="")

            result = focus_session("session-1", state_dir=Path(temp_dir), runner=runner)

            self.assertTrue(result.focused)
            self.assertIn("/dev/ttys001", scripts[0])
            self.assertIn("Terminal", scripts[0])

    def test_focus_session_activates_app_when_tty_search_misses(self) -> None:
        with TemporaryDirectory() as temp_dir:
            write_session_target(
                SessionTarget(
                    session="session-2",
                    mode="tui",
                    tty="/dev/ttys002",
                    terminal_program="Apple_Terminal",
                    terminal_app="Terminal",
                    pid=123,
                    started_at=1.0,
                ),
                state_dir=Path(temp_dir),
            )
            scripts: list[str] = []

            def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                scripts.append(args[-1])
                stdout = "focused\n" if "activate" in args[-1] else "not-found\n"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            result = focus_session("session-2", state_dir=Path(temp_dir), runner=runner)

            self.assertTrue(result.focused)
            self.assertIn("activate", scripts[-1])

    def test_focus_session_reports_missing_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = focus_session("missing", state_dir=Path(temp_dir))

        self.assertFalse(result.focused)
        self.assertIn("not found", result.detail)


if __name__ == "__main__":
    unittest.main()
