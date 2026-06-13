"""PTY wrapper for interactive Codex sessions."""

from __future__ import annotations

import os
import pty
import select
import signal
import subprocess
import sys
import termios
import tty
import uuid
from collections.abc import Sequence

from codex_speed.ansi import visible_byte_count
from codex_speed.events import DaemonAddress
from codex_speed.notifier_agent import AttentionAgent, from_env
from codex_speed.reporter import EventReporter
from codex_speed.tokens import estimate_tokens_from_bytes


def build_codex_tui_command(args: Sequence[str], *, codex_bin: str = "codex") -> list[str]:
    """Build an interactive Codex command."""

    parts = list(args)
    if parts and _is_codex_binary(parts[0]):
        return [codex_bin, *parts[1:]]
    return [codex_bin, *parts]


def run_tui(args: Sequence[str], address: DaemonAddress, *, codex_bin: str = "codex") -> int:
    """Run an interactive Codex TUI through a PTY."""

    if os.name != "posix":
        print("codex-speed tui currently requires a POSIX PTY", file=sys.stderr)
        return 2

    session = str(uuid.uuid4())
    reporter = EventReporter(address)
    attention = from_env()
    reporter.send({"type": "session_start", "mode": "tui", "session": session})
    attention.start_session(session, "tui")
    attention.start_background_checks()
    command = build_codex_tui_command(args, codex_bin=codex_bin)
    master_fd, slave_fd = pty.openpty()
    old_tty = termios.tcgetattr(sys.stdin.fileno()) if sys.stdin.isatty() else None
    try:
        process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    except OSError as exc:
        os.close(master_fd)
        os.close(slave_fd)
        print(f"codex-speed: failed to start Codex: {exc}", file=sys.stderr)
        reporter.send({"type": "child_exit", "mode": "tui", "session": session, "code": 127})
        reporter.send({"type": "session_end", "mode": "tui", "session": session})
        attention.end_session(session)
        attention.stop_background_checks()
        return 127
    os.close(slave_fd)
    _install_resize_forwarder(master_fd)

    try:
        if old_tty is not None:
            tty.setraw(sys.stdin.fileno())
        return_code = _pump_pty(process, master_fd, reporter, session, attention)
    except OSError as exc:
        print(f"codex-speed: TUI wrapper error: {exc}", file=sys.stderr)
        return_code = 1
    finally:
        if old_tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        os.close(master_fd)
        reporter.send({"type": "child_exit", "mode": "tui", "session": session, "code": return_code})
        reporter.send({"type": "session_end", "mode": "tui", "session": session})
        attention.end_session(session)
        attention.stop_background_checks()
    return return_code


def _install_resize_forwarder(master_fd: int) -> None:
    def _resize(_signum: int, _frame: object) -> None:
        try:
            import fcntl

            winsize = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            return

    signal.signal(signal.SIGWINCH, _resize)
    _resize(signal.SIGWINCH, None)


def _pump_pty(
    process: subprocess.Popen[bytes],
    master_fd: int,
    reporter: EventReporter,
    session: str,
    attention: AttentionAgent | None = None,
) -> int:
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    stdin_open = True
    while True:
        process_done = process.poll() is not None
        if process_done:
            readable, _, _ = select.select([master_fd], [], [], 0)
        else:
            read_fds = [master_fd]
            if stdin_open:
                read_fds.append(stdin_fd)
            readable, _, _ = select.select(read_fds, [], [], 0.1)
        if process_done and master_fd not in readable:
            break
        if stdin_open and not process_done and stdin_fd in readable:
            data = os.read(stdin_fd, 8192)
            if data:
                os.write(master_fd, data)
                _report_io(reporter, session, "input", "stdin", data)
                if attention is not None:
                    attention.observe_input(session)
            else:
                stdin_open = False
        if master_fd in readable:
            try:
                data = os.read(master_fd, 8192)
            except OSError:
                break
            if not data:
                break
            os.write(stdout_fd, data)
            _report_io(reporter, session, "output", "pty", data)
            if attention is not None:
                attention.observe_output(session, data)
    return process.wait()


def _report_io(
    reporter: EventReporter,
    session: str,
    direction: str,
    stream: str,
    data: bytes,
) -> None:
    visible = visible_byte_count(data)
    reporter.send(
        {
            "type": "io",
            "mode": "tui",
            "session": session,
            "direction": direction,
            "stream": stream,
            "bytes": len(data),
            "visible_bytes": visible,
            "estimated_tokens": estimate_tokens_from_bytes(visible),
        }
    )


def _is_codex_binary(value: str) -> bool:
    return value == "codex" or value.endswith("/codex")
