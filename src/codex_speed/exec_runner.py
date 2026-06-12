"""Wrapper for ``codex exec --json``."""

from __future__ import annotations

from collections.abc import Sequence

from codex_speed.events import DaemonAddress
from codex_speed.pipe_runner import run_pipe_command


def build_codex_exec_command(args: Sequence[str], *, codex_bin: str = "codex") -> list[str]:
    """Build a Codex exec command and ensure ``--json`` is present."""

    parts = list(args)
    if len(parts) >= 2 and _is_codex_binary(parts[0]) and parts[1] == "exec":
        command = [codex_bin, *parts[1:]]
        insert_at = 2
    elif parts and parts[0] == "exec":
        command = [codex_bin, *parts]
        insert_at = 2
    else:
        command = [codex_bin, "exec", *parts]
        insert_at = 2
    if "--json" not in command:
        command.insert(insert_at, "--json")
    return command


def run_exec(args: Sequence[str], address: DaemonAddress, *, codex_bin: str = "codex") -> int:
    """Run ``codex exec --json`` while reporting metrics."""

    command = build_codex_exec_command(args, codex_bin=codex_bin)
    return run_pipe_command(command, address, mode="exec", parse_stdout_jsonl=True)


def _is_codex_binary(value: str) -> bool:
    return value == "codex" or value.endswith("/codex")
