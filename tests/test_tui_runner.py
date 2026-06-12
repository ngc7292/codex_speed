import unittest
from typing import Any
from unittest.mock import patch

from codex_speed.tui_runner import _pump_pty


class FakeProcess:
    def __init__(self, wait_code: int = 0) -> None:
        self.wait_code = wait_code
        self.wait_calls = 0

    def poll(self) -> int:
        return self.wait_code

    def wait(self) -> int:
        self.wait_calls += 1
        return self.wait_code


class FakeReporter:
    def send(self, event: dict[str, Any]) -> None:
        raise AssertionError(f"unexpected event: {event}")


class TuiRunnerTests(unittest.TestCase):
    def test_pump_exits_when_pty_returns_eof_after_child_exit(self) -> None:
        process = FakeProcess(wait_code=0)
        master_fd = 123

        with (
            patch("codex_speed.tui_runner.select.select") as select_mock,
            patch("codex_speed.tui_runner.os.read", return_value=b"") as read_mock,
            patch("codex_speed.tui_runner.os.write") as write_mock,
            patch("codex_speed.tui_runner.sys.stdin.fileno", return_value=10),
            patch("codex_speed.tui_runner.sys.stdout.fileno", return_value=11),
        ):
            select_mock.side_effect = [
                ([master_fd], [], []),
                AssertionError("PTY EOF should end the pump immediately"),
            ]

            self.assertEqual(_pump_pty(process, master_fd, FakeReporter(), "s1"), 0)

        self.assertEqual(process.wait_calls, 1)
        read_mock.assert_called_once_with(master_fd, 8192)
        write_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
