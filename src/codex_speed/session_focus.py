"""Track wrapped session terminals and focus them on demand."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codex_speed.shim import default_state_dir, package_source_root


@dataclass(frozen=True)
class SessionTarget:
    """Terminal location metadata for one wrapped session."""

    session: str
    mode: str
    tty: str | None
    terminal_program: str | None
    terminal_app: str | None
    pid: int
    started_at: float
    ended_at: float | None = None


@dataclass(frozen=True)
class FocusResult:
    """Result of a terminal focus attempt."""

    focused: bool
    detail: str


class SessionRegistry:
    """Persist active session terminal metadata under the codex-speed state dir."""

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._state_dir = state_dir or default_state_dir()
        self._clock = clock or time.time

    def start_session(self, session: str, mode: str) -> None:
        """Record the current terminal target for a session."""

        target = capture_current_session_target(session, mode, clock=self._clock)
        write_session_target(target, state_dir=self._state_dir)

    def end_session(self, session: str) -> None:
        """Mark a session as ended while leaving metadata available for recent clicks."""

        target = load_session_target(session, state_dir=self._state_dir)
        if target is None:
            return
        write_session_target(
            SessionTarget(
                session=target.session,
                mode=target.mode,
                tty=target.tty,
                terminal_program=target.terminal_program,
                terminal_app=target.terminal_app,
                pid=target.pid,
                started_at=target.started_at,
                ended_at=self._clock(),
            ),
            state_dir=self._state_dir,
        )


def capture_current_session_target(
    session: str,
    mode: str,
    *,
    clock: Callable[[], float] | None = None,
) -> SessionTarget:
    """Return terminal metadata for the current wrapper process."""

    terminal_program = os.environ.get("TERM_PROGRAM")
    return SessionTarget(
        session=session,
        mode=mode,
        tty=current_tty(),
        terminal_program=terminal_program,
        terminal_app=terminal_app_from_program(terminal_program),
        pid=os.getpid(),
        started_at=(clock or time.time)(),
    )


def current_tty() -> str | None:
    """Return the first usable tty for stdin, stdout, or stderr."""

    for fd in (0, 1, 2):
        try:
            return os.ttyname(fd)
        except OSError:
            continue
    return None


def terminal_app_from_program(term_program: str | None) -> str | None:
    """Map TERM_PROGRAM values to AppleScript application names."""

    if term_program == "Apple_Terminal":
        return "Terminal"
    if term_program in {"iTerm.app", "iTerm2"}:
        return "iTerm2"
    if term_program:
        return term_program.removesuffix(".app")
    return None


def write_session_target(target: SessionTarget, *, state_dir: Path | None = None) -> None:
    """Write one session target atomically enough for local notification callbacks."""

    path = session_target_path(target.session, state_dir=state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(target), sort_keys=True), encoding="utf-8")


def load_session_target(session: str, *, state_dir: Path | None = None) -> SessionTarget | None:
    """Load session target metadata, if present and valid."""

    path = session_target_path(session, state_dir=state_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _target_from_payload(payload)


def session_target_path(session: str, *, state_dir: Path | None = None) -> Path:
    """Return the metadata file path for a safe session id."""

    return (state_dir or default_state_dir()) / "sessions" / f"{safe_session_id(session)}.json"


def safe_session_id(session: str) -> str:
    """Return a filesystem-safe session id or raise ValueError."""

    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not session or any(ch not in safe_chars for ch in session):
        raise ValueError("session id contains unsupported characters")
    return session


def build_focus_command(
    session: str,
    *,
    python_bin: str | None = None,
    source_root: Path | None = None,
) -> str:
    """Build a shell command suitable for terminal-notifier's click callback."""

    safe_session_id(session)
    python = python_bin or sys.executable
    root = source_root or package_source_root()
    return " ".join(
        [
            "env",
            f"PYTHONPATH={shlex.quote(str(root))}",
            shlex.quote(python),
            "-m",
            "codex_speed",
            "focus-session",
            "--quiet",
            shlex.quote(session),
        ]
    )


def focus_session(
    session: str,
    *,
    state_dir: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> FocusResult:
    """Focus the terminal associated with a tracked session."""

    try:
        target = load_session_target(session, state_dir=state_dir)
    except ValueError as exc:
        return FocusResult(False, str(exc))
    if target is None:
        return FocusResult(False, f"session metadata not found: {session}")
    if sys.platform != "darwin":
        return FocusResult(False, "terminal focus is currently implemented for macOS only")

    if target.tty:
        for app_name, script in _focus_scripts(target):
            result = _run_osascript(script, runner=runner)
            if result.focused:
                return FocusResult(True, f"focused {app_name} tty {target.tty}")

    if target.terminal_app:
        result = _run_osascript(_activate_app_script(target.terminal_app), runner=runner)
        if result.focused:
            return FocusResult(True, f"activated {target.terminal_app}")
    return FocusResult(False, f"terminal session not found for {session}")


def _target_from_payload(payload: dict[str, Any]) -> SessionTarget | None:
    session = payload.get("session")
    mode = payload.get("mode")
    pid = payload.get("pid")
    started_at = payload.get("started_at")
    if not isinstance(session, str) or not isinstance(mode, str):
        return None
    if not isinstance(pid, int) or not isinstance(started_at, (int, float)):
        return None
    return SessionTarget(
        session=session,
        mode=mode,
        tty=_optional_string(payload.get("tty")),
        terminal_program=_optional_string(payload.get("terminal_program")),
        terminal_app=_optional_string(payload.get("terminal_app")),
        pid=pid,
        started_at=float(started_at),
        ended_at=_optional_float(payload.get("ended_at")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _focus_scripts(target: SessionTarget) -> list[tuple[str, str]]:
    if target.tty is None:
        return []
    terminal = ("Terminal", _terminal_focus_script(target.tty))
    iterm = ("iTerm2", _iterm_focus_script(target.tty))
    if target.terminal_app == "iTerm2":
        return [iterm, terminal]
    if target.terminal_app == "Terminal":
        return [terminal, iterm]
    return [terminal, iterm]


def _run_osascript(
    script: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> FocusResult:
    try:
        result = runner(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return FocusResult(False, str(exc))
    output = (result.stdout or "").strip()
    return FocusResult(output == "focused", output or "no result")


def _terminal_focus_script(tty: str) -> str:
    escaped_tty = _applescript_string(tty)
    return f"""
tell application "Terminal"
    repeat with theWindow in windows
        repeat with theTab in tabs of theWindow
            if tty of theTab is {escaped_tty} then
                set selected tab of theWindow to theTab
                set index of theWindow to 1
                activate
                return "focused"
            end if
        end repeat
    end repeat
end tell
return "not-found"
"""


def _iterm_focus_script(tty: str) -> str:
    escaped_tty = _applescript_string(tty)
    return f"""
tell application "iTerm2"
    repeat with theWindow in windows
        repeat with theTab in tabs of theWindow
            repeat with theSession in sessions of theTab
                if tty of theSession is {escaped_tty} then
                    tell theWindow to select
                    tell theTab to select
                    tell theSession to select
                    activate
                    return "focused"
                end if
            end repeat
        end repeat
    end repeat
end tell
return "not-found"
"""


def _activate_app_script(app_name: str) -> str:
    return f"""
tell application {_applescript_string(app_name)}
    activate
end tell
return "focused"
"""


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
