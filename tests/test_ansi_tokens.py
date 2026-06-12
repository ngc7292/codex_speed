import unittest

from codex_speed.ansi import strip_ansi, visible_byte_count
from codex_speed.tokens import estimate_tokens_from_bytes


class AnsiTokenTests(unittest.TestCase):
    def test_strip_ansi_removes_sgr_sequences(self) -> None:
        self.assertEqual(strip_ansi("\x1b[31mred\x1b[0m"), "red")

    def test_visible_byte_count_handles_unicode(self) -> None:
        self.assertEqual(
            visible_byte_count("你\x1b[0m好".encode("utf-8")),
            len("你好".encode("utf-8")),
        )

    def test_estimate_tokens_from_bytes_rounds_up(self) -> None:
        self.assertEqual(estimate_tokens_from_bytes(0), 0)
        self.assertEqual(estimate_tokens_from_bytes(1), 1)
        self.assertEqual(estimate_tokens_from_bytes(5), 2)


if __name__ == "__main__":
    unittest.main()
