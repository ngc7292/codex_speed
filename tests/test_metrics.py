import unittest

from codex_speed.metrics import MetricsRegistry


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


if __name__ == "__main__":
    unittest.main()
