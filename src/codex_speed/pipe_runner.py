"""Pipe-based wrapper for non-interactive Codex commands."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence

from codex_speed.ansi import visible_byte_count
from codex_speed.events import DaemonAddress
from codex_speed.jsonl import extract_turn_usage, parse_json_line
from codex_speed.reporter import EventReporter
from codex_speed.tokens import estimate_tokens_from_bytes


def run_pipe_command(
    command: Sequence[str],
    address: DaemonAddress,
    *,
    mode: str = "exec",
    parse_stdout_jsonl: bool = False,
) -> int:
    """Run a command with stdout/stderr pipes while reporting metrics.

    This preserves the child's stdout/stderr bytes exactly, but the child sees
    stdout/stderr as pipes rather than a terminal. Use the PTY runner for the
    interactive Codex UI.
    """

    session = str(uuid.uuid4())
    reporter = EventReporter(address)
    reporter.send({"type": "session_start", "mode": mode, "session": session})
    start_time = time.monotonic()
    stdin_is_piped = not sys.stdin.isatty()
    child_stdin = subprocess.PIPE if stdin_is_piped else None
    try:
        process = subprocess.Popen(
            list(command),
            stdin=child_stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as exc:
        print(f"codex-speed: failed to start Codex: {exc}", file=sys.stderr)
        reporter.send({"type": "session_end", "mode": mode, "session": session})
        return 127

    assert process.stdout is not None
    assert process.stderr is not None

    threads = [
        threading.Thread(
            target=_read_stdout,
            args=(process.stdout, reporter, session, mode, parse_stdout_jsonl),
            daemon=True,
        ),
        threading.Thread(
            target=_read_stderr,
            args=(process.stderr, reporter, session, mode),
            daemon=True,
        ),
    ]
    if stdin_is_piped:
        assert process.stdin is not None
        threads.append(
            threading.Thread(
                target=_copy_stdin,
                args=(process.stdin, reporter, session, mode),
                daemon=True,
            )
        )
    for thread in threads:
        thread.start()
    return_code = process.wait()
    for thread in threads:
        thread.join(timeout=2.0)
    elapsed = time.monotonic() - start_time
    reporter.send({"type": "turn_duration", "mode": mode, "session": session, "seconds": elapsed})
    reporter.send({"type": "child_exit", "mode": mode, "session": session, "code": return_code})
    reporter.send({"type": "session_end", "mode": mode, "session": session})
    return return_code


def _copy_stdin(
    child_stdin: object,
    reporter: EventReporter,
    session: str,
    mode: str,
) -> None:
    writable = child_stdin
    try:
        while True:
            data = sys.stdin.buffer.read(8192)
            if not data:
                break
            writable.write(data)  # type: ignore[attr-defined]
            writable.flush()  # type: ignore[attr-defined]
            _report_io(reporter, session, mode, "input", "stdin", data)
    except BrokenPipeError:
        return
    finally:
        try:
            writable.close()  # type: ignore[attr-defined]
        except OSError:
            pass


def _read_stdout(
    stdout: object,
    reporter: EventReporter,
    session: str,
    mode: str,
    parse_jsonl: bool,
) -> None:
    readable = stdout
    buffer = b""
    while True:
        chunk = readable.read(8192)  # type: ignore[attr-defined]
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        _report_io(reporter, session, mode, "output", "stdout", chunk)
        if parse_jsonl:
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                _handle_json_line(line, reporter, session, mode)
    if parse_jsonl and buffer:
        _handle_json_line(buffer, reporter, session, mode)


def _read_stderr(stderr: object, reporter: EventReporter, session: str, mode: str) -> None:
    readable = stderr
    while True:
        chunk = readable.read(8192)  # type: ignore[attr-defined]
        if not chunk:
            break
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()
        _report_io(reporter, session, mode, "output", "stderr", chunk)


def _handle_json_line(line: bytes, reporter: EventReporter, session: str, mode: str) -> None:
    try:
        event = parse_json_line(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reporter.send({"type": "parse_error", "mode": mode, "session": session, "source": "jsonl"})
        return
    if event is None:
        return
    usage = extract_turn_usage(event)
    if usage:
        reporter.send({"type": "usage", "mode": mode, "session": session, "usage": usage})


def _report_io(
    reporter: EventReporter,
    session: str,
    mode: str,
    direction: str,
    stream: str,
    data: bytes,
) -> None:
    visible = visible_byte_count(data)
    reporter.send(
        {
            "type": "io",
            "mode": mode,
            "session": session,
            "direction": direction,
            "stream": stream,
            "bytes": len(data),
            "visible_bytes": visible,
            "estimated_tokens": estimate_tokens_from_bytes(visible),
        }
    )
