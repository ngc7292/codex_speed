import json
import unittest

from codex_speed.jsonl import extract_turn_usage, parse_json_line


class JsonlTests(unittest.TestCase):
    def test_parse_json_line_returns_object(self) -> None:
        self.assertEqual(parse_json_line(b'{"type":"turn.started"}\n'), {"type": "turn.started"})

    def test_parse_json_line_ignores_blank(self) -> None:
        self.assertIsNone(parse_json_line(b"\n"))

    def test_parse_json_line_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            parse_json_line(b"{not json}")

    def test_extract_turn_usage(self) -> None:
        usage = extract_turn_usage(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                },
            }
        )
        self.assertEqual(
            usage,
            {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "reasoning_output_tokens": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
