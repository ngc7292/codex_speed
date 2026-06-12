"""Minimal Prometheus registry for codex-speed."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


LabelValues = tuple[tuple[str, str], ...]


def _labels(**labels: str | int) -> LabelValues:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: LabelValues) -> str:
    if not labels:
        return ""
    body = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels)
    return f"{{{body}}}"


def _format_float(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value.is_integer():
        return str(int(value))
    return repr(value)


@dataclass
class CounterMetric:
    """Prometheus counter."""

    name: str
    help_text: str
    samples: dict[LabelValues, float] = field(default_factory=dict)

    def inc(self, amount: float, **labels: str | int) -> None:
        """Increase the counter by ``amount``."""

        if amount < 0:
            raise ValueError("counter increments must be non-negative")
        key = _labels(**labels)
        self.samples[key] = self.samples.get(key, 0.0) + amount


@dataclass
class GaugeMetric:
    """Prometheus gauge."""

    name: str
    help_text: str
    samples: dict[LabelValues, float] = field(default_factory=dict)

    def set(self, value: float, **labels: str | int) -> None:
        """Set a gauge value."""

        self.samples[_labels(**labels)] = value

    def inc(self, amount: float, **labels: str | int) -> None:
        """Increase a gauge value."""

        key = _labels(**labels)
        self.samples[key] = self.samples.get(key, 0.0) + amount


@dataclass
class HistogramMetric:
    """Prometheus histogram with fixed buckets."""

    name: str
    help_text: str
    buckets: tuple[float, ...]
    counts: dict[LabelValues, list[int]] = field(default_factory=dict)
    sums: dict[LabelValues, float] = field(default_factory=dict)

    def observe(self, value: float, **labels: str | int) -> None:
        """Observe one value."""

        key = _labels(**labels)
        counts = self.counts.setdefault(key, [0 for _ in self.buckets])
        for index, bucket in enumerate(self.buckets):
            if value <= bucket:
                counts[index] += 1
        self.sums[key] = self.sums.get(key, 0.0) + value


@dataclass
class ActiveSession:
    """Daemon-local state for active session throughput gauges."""

    mode: str
    started_at: float
    estimated_output_tokens: float = 0.0
    exact_output_tokens: float = 0.0
    estimated_output_seen: bool = False
    exact_output_seen: bool = False


class MetricsRegistry:
    """In-memory Prometheus registry tailored to codex-speed metrics."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._active_sessions: dict[str, ActiveSession] = {}
        self.sessions_active = GaugeMetric(
            "codex_speed_sessions_active",
            "Active codex-speed wrapped sessions.",
        )
        self.io_bytes_total = CounterMetric(
            "codex_speed_io_bytes_total",
            "Raw bytes observed at wrapped Codex process boundaries.",
        )
        self.visible_bytes_total = CounterMetric(
            "codex_speed_visible_bytes_total",
            "Visible UTF-8 bytes after terminal control sequence stripping.",
        )
        self.estimated_tokens_total = CounterMetric(
            "codex_speed_estimated_tokens_total",
            "Estimated token count from local byte heuristic.",
        )
        self.usage_tokens_total = CounterMetric(
            "codex_speed_usage_tokens_total",
            "Exact Codex token usage emitted by Codex JSON events.",
        )
        self.turn_duration_seconds = HistogramMetric(
            "codex_speed_turn_duration_seconds",
            "Turn duration in seconds.",
            buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, math.inf),
        )
        self.child_exits_total = CounterMetric(
            "codex_speed_child_exits_total",
            "Wrapped Codex child process exits.",
        )
        self.parse_errors_total = CounterMetric(
            "codex_speed_parse_errors_total",
            "Input parse errors while collecting Codex events.",
        )
        self.events_total = CounterMetric(
            "codex_speed_events_total",
            "Events accepted by the codex-speed daemon.",
        )
        self.started_at = self._clock()

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply one collector event to the registry."""

        event_type = str(event.get("type", "unknown"))
        mode = _safe_label(event.get("mode"), default="unknown")
        session = _safe_label(event.get("session"), default="unknown")

        with self._lock:
            self.events_total.inc(1, type=event_type)
            if event_type == "session_start":
                self.sessions_active.inc(1, mode=mode)
                self._active_sessions[session] = ActiveSession(
                    mode=mode,
                    started_at=self._clock(),
                )
            elif event_type == "session_end":
                self.sessions_active.inc(-1, mode=mode)
                self._active_sessions.pop(session, None)
            elif event_type == "io":
                self._apply_io_event(event, mode, session)
            elif event_type == "usage":
                self._apply_usage_event(event, mode, session)
            elif event_type == "turn_duration":
                duration = _non_negative_float(event.get("seconds"))
                if duration is not None:
                    self.turn_duration_seconds.observe(duration, mode=mode)
            elif event_type == "child_exit":
                code = _safe_label(event.get("code"), default="unknown")
                self.child_exits_total.inc(1, mode=mode, code=code)
            elif event_type == "parse_error":
                source = _safe_label(event.get("source"), default="unknown")
                self.parse_errors_total.inc(1, mode=mode, source=source)

    def render(self) -> str:
        """Render the registry in Prometheus text exposition format."""

        with self._lock:
            lines: list[str] = []
            for metric in (
                self.sessions_active,
                self.io_bytes_total,
                self.visible_bytes_total,
                self.estimated_tokens_total,
                self.usage_tokens_total,
                self.child_exits_total,
                self.parse_errors_total,
                self.events_total,
            ):
                lines.extend(_render_simple_metric(metric))
            lines.extend(_render_active_session_tgs(self._active_sessions, self._clock()))
            lines.extend(_render_histogram(self.turn_duration_seconds))
            lines.extend(
                [
                    "# HELP codex_speed_daemon_uptime_seconds Daemon uptime in seconds.",
                    "# TYPE codex_speed_daemon_uptime_seconds gauge",
                    f"codex_speed_daemon_uptime_seconds {_format_float(self._clock() - self.started_at)}",
                ]
            )
            return "\n".join(lines) + "\n"

    def _apply_io_event(self, event: dict[str, Any], mode: str, session: str) -> None:
        direction = _safe_label(event.get("direction"), default="unknown")
        stream = _safe_label(event.get("stream"), default="unknown")
        raw_bytes = _non_negative_float(event.get("bytes"))
        visible_bytes = _non_negative_float(event.get("visible_bytes"))
        estimated_tokens = _non_negative_float(event.get("estimated_tokens"))
        if raw_bytes is not None:
            self.io_bytes_total.inc(
                raw_bytes,
                mode=mode,
                direction=direction,
                stream=stream,
                session=session,
            )
        if visible_bytes is not None:
            self.visible_bytes_total.inc(
                visible_bytes,
                mode=mode,
                direction=direction,
                session=session,
            )
        if estimated_tokens is not None:
            self.estimated_tokens_total.inc(
                estimated_tokens,
                mode=mode,
                direction=direction,
                session=session,
                accuracy="estimated",
            )
            if direction == "output":
                active_session = self._active_sessions.get(session)
                if active_session is not None:
                    active_session.estimated_output_tokens += estimated_tokens
                    active_session.estimated_output_seen = True

    def _apply_usage_event(self, event: dict[str, Any], mode: str, session: str) -> None:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            return
        key_map = {
            "input_tokens": "input",
            "cached_input_tokens": "cached_input",
            "output_tokens": "output",
            "reasoning_output_tokens": "reasoning_output",
        }
        for source_key, kind in key_map.items():
            value = _non_negative_float(usage.get(source_key))
            if value is not None:
                self.usage_tokens_total.inc(
                    value,
                    mode=mode,
                    kind=kind,
                    session=session,
                    accuracy="exact",
                )
                if source_key == "output_tokens":
                    active_session = self._active_sessions.get(session)
                    if active_session is not None:
                        active_session.exact_output_tokens += value
                        active_session.exact_output_seen = True


def _safe_label(value: object, *, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    if not text:
        return default
    return text[:120]


def _non_negative_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _render_simple_metric(metric: CounterMetric | GaugeMetric) -> list[str]:
    metric_type = "counter" if isinstance(metric, CounterMetric) else "gauge"
    lines = [
        f"# HELP {metric.name} {metric.help_text}",
        f"# TYPE {metric.name} {metric_type}",
    ]
    for labels, value in sorted(metric.samples.items()):
        lines.append(f"{metric.name}{_format_labels(labels)} {_format_float(value)}")
    return lines


def _render_active_session_tgs(active_sessions: dict[str, ActiveSession], now: float) -> list[str]:
    help_line = (
        "# HELP codex_speed_session_output_tokens_per_second "
        "Active session average output tokens per second."
    )
    lines = [
        help_line,
        "# TYPE codex_speed_session_output_tokens_per_second gauge",
    ]
    for session, active_session in sorted(active_sessions.items()):
        elapsed = max(now - active_session.started_at, 0.0)
        if active_session.estimated_output_seen:
            value = active_session.estimated_output_tokens / elapsed if elapsed > 0 else 0.0
            labels = _labels(mode=active_session.mode, session=session, accuracy="estimated")
            lines.append(
                f"codex_speed_session_output_tokens_per_second{_format_labels(labels)} "
                f"{_format_float(value)}"
            )
        if active_session.exact_output_seen:
            value = active_session.exact_output_tokens / elapsed if elapsed > 0 else 0.0
            labels = _labels(mode=active_session.mode, session=session, accuracy="exact")
            lines.append(
                f"codex_speed_session_output_tokens_per_second{_format_labels(labels)} "
                f"{_format_float(value)}"
            )
    return lines


def _render_histogram(metric: HistogramMetric) -> list[str]:
    lines = [
        f"# HELP {metric.name} {metric.help_text}",
        f"# TYPE {metric.name} histogram",
    ]
    for labels, counts in sorted(metric.counts.items()):
        base_labels = dict(labels)
        total = 0
        for bucket, count in zip(metric.buckets, counts, strict=True):
            total = count
            bucket_labels = _labels(**base_labels, le=_format_float(bucket))
            lines.append(f"{metric.name}_bucket{_format_labels(bucket_labels)} {total}")
        lines.append(f"{metric.name}_count{_format_labels(labels)} {total}")
        lines.append(
            f"{metric.name}_sum{_format_labels(labels)} "
            f"{_format_float(metric.sums.get(labels, 0.0))}"
        )
    return lines
