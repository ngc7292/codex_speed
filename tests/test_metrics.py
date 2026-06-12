import unittest

from codex_speed.metrics import MetricsRegistry


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class MetricsTests(unittest.TestCase):
    def test_registry_applies_io_and_usage_events(self) -> None:
        registry = MetricsRegistry()
        registry.apply_event({"type": "session_start", "mode": "exec", "session": "s1"})
        registry.apply_event(
            {
                "type": "io",
                "mode": "exec",
                "session": "s1",
                "direction": "output",
                "stream": "stdout",
                "bytes": 12,
                "visible_bytes": 10,
                "estimated_tokens": 3,
            }
        )
        registry.apply_event(
            {
                "type": "usage",
                "mode": "exec",
                "session": "s1",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
        )
        rendered = registry.render()
        self.assertIn('codex_speed_sessions_active{mode="exec"} 1', rendered)
        self.assertIn(
            'codex_speed_io_bytes_total{direction="output",mode="exec",session="s1",stream="stdout"} 12',
            rendered,
        )
        self.assertIn(
            'codex_speed_usage_tokens_total{accuracy="exact",kind="output",mode="exec",session="s1"} 4',
            rendered,
        )

    def test_registry_counts_parse_errors(self) -> None:
        registry = MetricsRegistry()
        registry.apply_event({"type": "parse_error", "mode": "exec", "source": "jsonl"})
        self.assertIn(
            'codex_speed_parse_errors_total{mode="exec",source="jsonl"} 1',
            registry.render(),
        )

    def test_registry_renders_active_estimated_output_tgs(self) -> None:
        clock = FakeClock(100.0)
        registry = MetricsRegistry(clock=clock)
        registry.apply_event({"type": "session_start", "mode": "tui", "session": "s1"})
        registry.apply_event(
            {
                "type": "io",
                "mode": "tui",
                "session": "s1",
                "direction": "output",
                "stream": "pty",
                "bytes": 80,
                "visible_bytes": 80,
                "estimated_tokens": 20,
            }
        )

        clock.now = 110.0
        expected = (
            'codex_speed_session_output_tokens_per_second{accuracy="estimated",'
            'mode="tui",session="s1"} 2'
        )
        self.assertIn(
            expected,
            registry.render(),
        )

    def test_registry_renders_active_exact_output_tgs_when_usage_is_available(self) -> None:
        clock = FakeClock(200.0)
        registry = MetricsRegistry(clock=clock)
        registry.apply_event({"type": "session_start", "mode": "exec", "session": "s1"})
        registry.apply_event(
            {
                "type": "usage",
                "mode": "exec",
                "session": "s1",
                "usage": {"input_tokens": 10, "output_tokens": 15},
            }
        )

        clock.now = 210.0
        expected = (
            'codex_speed_session_output_tokens_per_second{accuracy="exact",'
            'mode="exec",session="s1"} 1.5'
        )
        self.assertIn(
            expected,
            registry.render(),
        )

    def test_registry_stops_rendering_tgs_after_session_end(self) -> None:
        clock = FakeClock(300.0)
        registry = MetricsRegistry(clock=clock)
        registry.apply_event({"type": "session_start", "mode": "exec", "session": "s1"})
        registry.apply_event(
            {
                "type": "io",
                "mode": "exec",
                "session": "s1",
                "direction": "output",
                "stream": "stdout",
                "bytes": 40,
                "visible_bytes": 40,
                "estimated_tokens": 10,
            }
        )
        registry.apply_event({"type": "session_end", "mode": "exec", "session": "s1"})

        self.assertNotIn("codex_speed_session_output_tokens_per_second{", registry.render())


if __name__ == "__main__":
    unittest.main()
