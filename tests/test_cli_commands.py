import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_speed.auto_runner import classify_codex_args
from codex_speed.cli import parse_daemon_bind, parse_listen
from codex_speed.exec_runner import build_codex_exec_command
from codex_speed.shim import install_shim, render_shim
from codex_speed.tui_runner import build_codex_tui_command


class CliCommandTests(unittest.TestCase):
    def test_build_exec_command_injects_json(self) -> None:
        self.assertEqual(
            build_codex_exec_command(["hello"]),
            ["codex", "exec", "--json", "hello"],
        )

    def test_build_exec_command_preserves_existing_codex_exec(self) -> None:
        self.assertEqual(
            build_codex_exec_command(["codex", "exec", "--json", "hello"]),
            ["codex", "exec", "--json", "hello"],
        )

    def test_build_exec_command_uses_real_codex_path(self) -> None:
        self.assertEqual(
            build_codex_exec_command(["exec", "hello"], codex_bin="/opt/homebrew/bin/codex"),
            ["/opt/homebrew/bin/codex", "exec", "--json", "hello"],
        )

    def test_build_tui_command_prefixes_codex(self) -> None:
        self.assertEqual(build_codex_tui_command(["--no-alt-screen"]), ["codex", "--no-alt-screen"])

    def test_build_tui_command_uses_real_codex_path(self) -> None:
        self.assertEqual(
            build_codex_tui_command(["--no-alt-screen"], codex_bin="/opt/homebrew/bin/codex"),
            ["/opt/homebrew/bin/codex", "--no-alt-screen"],
        )

    def test_parse_listen_accepts_loopback(self) -> None:
        address = parse_listen("127.0.0.1:9467")
        self.assertEqual(address.host, "127.0.0.1")
        self.assertEqual(address.port, 9467)

    def test_parse_listen_rejects_container_bind_address(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_listen("0.0.0.0:9467")

    def test_parse_daemon_bind_accepts_container_bind_address(self) -> None:
        address = parse_daemon_bind("0.0.0.0:9467")
        self.assertEqual(address.host, "0.0.0.0")
        self.assertEqual(address.port, 9467)

    def test_auto_routes_exec_after_global_options_to_pipe(self) -> None:
        route = classify_codex_args(["-C", "/tmp/work", "exec", "say hi"])
        self.assertEqual(route.kind, "pipe")
        self.assertEqual(route.subcommand, "exec")
        self.assertFalse(route.parse_stdout_jsonl)

    def test_auto_routes_explicit_json_exec_to_pipe_with_json_parse(self) -> None:
        route = classify_codex_args(["exec", "--json", "say hi"])
        self.assertEqual(route.kind, "pipe")
        self.assertTrue(route.parse_stdout_jsonl)

    def test_auto_bypasses_protocol_and_config_commands(self) -> None:
        for args in (["mcp-server"], ["completion", "zsh"], ["login"], ["doctor"]):
            with self.subTest(args=args):
                self.assertEqual(classify_codex_args(args).kind, "bypass")

    def test_auto_uses_tui_for_default_prompt(self) -> None:
        route = classify_codex_args(["write", "tests"])
        self.assertEqual(route.kind, "tui")

    def test_render_shim_points_to_auto_runner_and_real_codex(self) -> None:
        script = render_shim(
            "/opt/homebrew/bin/codex",
            Path("/tmp/codex_guide/src"),
            "/usr/bin/python3",
        )
        self.assertIn("CODEX_SPEED_REAL_CODEX=/opt/homebrew/bin/codex", script)
        self.assertIn('exec /usr/bin/python3 -m codex_speed auto -- "$@"', script)
        self.assertIn('CODEX_SPEED_DISABLE:-', script)

    def test_install_shim_writes_executable_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_codex = root / "real" / "codex"
            real_codex.parent.mkdir()
            real_codex.write_text("#!/bin/sh\n", encoding="utf-8")
            real_codex.chmod(0o755)
            shim_path = install_shim(
                real_codex=str(real_codex),
                shim_dir=root / "shim",
                source_root=Path("/tmp/codex_guide/src"),
                python_bin="/usr/bin/python3",
            )
            self.assertTrue(shim_path.exists())
            self.assertTrue(shim_path.stat().st_mode & 0o111)
            self.assertIn(str(real_codex), shim_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
