"""Desktop attention notifications for wrapped Codex sessions."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from codex_speed.ansi import strip_ansi

DEFAULT_PAUSE_SECONDS = 120.0
DEFAULT_DEDUPE_SECONDS = 300.0
DEFAULT_CHECK_INTERVAL_SECONDS = 2.0

FALSE_VALUES = {"", "0", "false", "FALSE", "no", "NO", "off", "OFF"}

PERMISSION_PROMPT_PATTERNS = (
    re.compile(r"\bapproval\b", re.IGNORECASE),
    re.compile(r"\bapprove\b", re.IGNORECASE),
    re.compile(r"\bpermission\s+(required|request|prompt)\b", re.IGNORECASE),
    re.compile(r"\brequesting\s+permission\b", re.IGNORECASE),
    re.compile(r"\brequires?\s+(approval|permission)\b", re.IGNORECASE),
    re.compile(r"\bwaiting\s+for\s+(approval|permission|confirmation)\b", re.IGNORECASE),
    re.compile(r"\bdo\s+you\s+want\s+to\s+(allow|approve|continue|run|execute)\b", re.IGNORECASE),
    re.compile(r"\b(allow|approve|run|execute)\b.{0,80}\?", re.IGNORECASE | re.DOTALL),
    re.compile(r"(需要|请求).{0,20}(权限|确认|批准)"),
    re.compile(r"(等待|暂停).{0,20}(确认|权限|批准)"),
)

PAUSED_PROMPT_PATTERNS = (
    re.compile(r"\bsession\s+paused\b", re.IGNORECASE),
    re.compile(r"\bpaused\b.{0,80}\b(user\s+input|input|resume|continue)\b", re.IGNORECASE),
    re.compile(r"\bwaiting\s+for\s+(user\s+)?input\b", re.IGNORECASE),
    re.compile(r"\bpress\s+(enter|return)\s+to\s+continue\b", re.IGNORECASE),
    re.compile(r"(暂停|等待).{0,20}(输入|继续|恢复)"),
)


class Notifier(Protocol):
    """Notification sink."""

    def notify(self, title: str, message: str) -> None:
        """Send one user-visible notification."""


class StderrNotifier:
    """Fallback notifier that writes to stderr."""

    def notify(self, title: str, message: str) -> None:
        print(f"codex-speed: {title}: {message}", file=sys.stderr)


class MacOSNotifier:
    """macOS notification sink using AppleScript."""

    def __init__(self, *, fallback: Notifier | None = None) -> None:
        self._fallback = fallback or StderrNotifier()

    def notify(self, title: str, message: str) -> None:
        script = (
            f"display notification {_applescript_string(message)} "
            f"with title {_applescript_string(title)}"
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            self._fallback.notify(title, message)


def default_notifier() -> Notifier:
    """Return the best notifier for this host."""

    if sys.platform == "darwin":
        return MacOSNotifier()
    return StderrNotifier()


@dataclass
class AttentionSession:
    """Mutable attention state for one wrapped Codex session."""

    session: str
    mode: str
    started_at: float
    last_activity_at: float
    output_seen: bool = False
    notifications: dict[str, float] = field(default_factory=dict)


class AttentionAgent:
    """Detect permission prompts and stalled sessions, then notify the desktop."""

    def __init__(
        self,
        *,
        notifier: Notifier | None = None,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        dedupe_seconds: float = DEFAULT_DEDUPE_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        clock: Callable[[], float] | None = None,
        enabled: bool = True,
    ) -> None:
        self._notifier = notifier or default_notifier()
        self._pause_seconds = max(pause_seconds, 1.0)
        self._dedupe_seconds = max(dedupe_seconds, 1.0)
        self._check_interval_seconds = max(check_interval_seconds, 0.1)
        self._clock = clock or time.monotonic
        self._enabled = enabled
        self._sessions: dict[str, AttentionSession] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start_session(self, session: str, mode: str) -> None:
        """Track a new wrapped Codex session."""

        if not self._enabled:
            return
        now = self._clock()
        with self._lock:
            self._sessions[session] = AttentionSession(
                session=session,
                mode=mode,
                started_at=now,
                last_activity_at=now,
            )

    def end_session(self, session: str) -> None:
        """Stop tracking a wrapped Codex session."""

        if not self._enabled:
            return
        with self._lock:
            self._sessions.pop(session, None)

    def observe_input(self, session: str) -> None:
        """Mark user input activity for a session."""

        self._touch(session)

    def observe_output(self, session: str, data: bytes) -> None:
        """Scan one output chunk for attention signals without storing it."""

        if not self._enabled:
            return
        text = _decode_visible_text(data)
        permission_attention = text_needs_permission_attention(text)
        paused_attention = text_needs_paused_attention(text)
        with self._lock:
            tracked = self._sessions.get(session)
            if tracked is None:
                return
            tracked.last_activity_at = self._clock()
            tracked.output_seen = True
        if permission_attention:
            self._notify_once(
                session,
                "permission",
                "Codex Needs Attention",
                "Codex appears to be waiting for approval or permission.",
            )
        elif paused_attention:
            self._notify_once(
                session,
                "paused",
                "Codex Is Paused",
                "Codex appears to be waiting for input.",
            )

    def check_idle(self) -> None:
        """Notify for active sessions with no recent activity."""

        if not self._enabled:
            return
        now = self._clock()
        stale_sessions: list[str] = []
        with self._lock:
            for session, tracked in self._sessions.items():
                if not tracked.output_seen:
                    continue
                if session_is_inactive(
                    last_activity_at=tracked.last_activity_at,
                    now=now,
                    pause_seconds=self._pause_seconds,
                    output_seen=tracked.output_seen,
                ):
                    stale_sessions.append(session)
        for session in stale_sessions:
            self._notify_once(
                session,
                "paused",
                "Codex May Be Waiting",
                "No Codex terminal activity has been seen recently.",
            )

    def start_background_checks(self) -> None:
        """Start idle checks in a background thread."""

        if not self._enabled or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="codex-speed-attention", daemon=True)
        self._thread.start()

    def stop_background_checks(self) -> None:
        """Stop the background idle checker."""

        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._check_interval_seconds):
            self.check_idle()

    def _touch(self, session: str) -> None:
        if not self._enabled:
            return
        with self._lock:
            tracked = self._sessions.get(session)
            if tracked is not None:
                tracked.last_activity_at = self._clock()

    def _notify_once(self, session: str, kind: str, title: str, message: str) -> None:
        now = self._clock()
        key = f"{session}:{kind}"
        with self._lock:
            tracked = self._sessions.get(session)
            if tracked is None:
                return
            last_notified_at = tracked.notifications.get(key)
            if last_notified_at is not None and now - last_notified_at < self._dedupe_seconds:
                return
            tracked.notifications[key] = now
        self._notifier.notify(title, f"{message} Session: {session[:8]}.")


def text_needs_permission_attention(text: str) -> bool:
    """Return true when output text looks like an approval or permission prompt."""

    if not text:
        return False
    compact = " ".join(text.split())
    return any(pattern.search(compact) is not None for pattern in PERMISSION_PROMPT_PATTERNS)


def text_needs_paused_attention(text: str) -> bool:
    """Return true when output text looks like an explicit paused/waiting prompt."""

    if not text:
        return False
    compact = " ".join(text.split())
    return any(pattern.search(compact) is not None for pattern in PAUSED_PROMPT_PATTERNS)


def session_is_inactive(
    *,
    last_activity_at: float,
    now: float,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    active: bool = True,
    output_seen: bool = True,
) -> bool:
    """Return true when an active session has been quiet long enough to notify."""

    return active and output_seen and now - last_activity_at >= pause_seconds


def from_env(*, notifier: Notifier | None = None) -> AttentionAgent:
    """Build an attention agent using CODEX_SPEED_NOTIFY_* environment settings."""

    enabled = os.environ.get("CODEX_SPEED_NOTIFY", "1") not in FALSE_VALUES
    return AttentionAgent(
        notifier=notifier,
        pause_seconds=_float_env("CODEX_SPEED_NOTIFY_PAUSE_SECONDS", DEFAULT_PAUSE_SECONDS),
        dedupe_seconds=_float_env("CODEX_SPEED_NOTIFY_DEDUPE_SECONDS", DEFAULT_DEDUPE_SECONDS),
        check_interval_seconds=_float_env(
            "CODEX_SPEED_NOTIFY_CHECK_INTERVAL_SECONDS",
            DEFAULT_CHECK_INTERVAL_SECONDS,
        ),
        enabled=enabled,
    )


def send_test_notification(*, notifier: Notifier | None = None) -> None:
    """Send one notification so users can verify desktop permissions."""

    sink = notifier or default_notifier()
    sink.notify("Codex Notification Test", "codex-speed desktop notifications are enabled.")


def _decode_visible_text(data: bytes) -> str:
    return strip_ansi(data.decode("utf-8", errors="ignore"))


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return parsed


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
