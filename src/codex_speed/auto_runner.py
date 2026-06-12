"""Automatic routing for a Codex PATH shim."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codex_speed.events import DaemonAddress
from codex_speed.pipe_runner import run_pipe_command
from codex_speed.shim import default_log_path, default_state_dir, default_shim_dir, find_real_codex
from codex_speed.tui_runner import run_tui

RouteKind = Literal["bypass", "pipe", "tui"]

PIPE_SUBCOMMANDS = {"exec", "e", "review"}
TUI_SUBCOMMANDS = {"resume", "fork"}
BYPASS_SUBCOMMANDS = {
    "a",
    "app",
    "app-server",
    "apply",
    "archive",
    "cloud",
    "completion",
    "debug",
    "doctor",
    "exec-server",
    "features",
    "help",
    "login",
    "logout",
    "mcp",
    "mcp-server",
    "plugin",
    "remote-control",
    "sandbox",
    "unarchive",
    "update",
}
HELP_VERSION_FLAGS = {"-h", "--help", "-V", "--version"}
LONG_OPTIONS_WITH_VALUE = {
    "--add-dir",
    "--ask-for-approval",
    "--cd",
    "--config",
    "--disable",
    "--enable",
    "--image",
    "--local-provider",
    "--model",
    "--profile",
    "--remote",
    "--remote-auth-token-env",
    "--sandbox",
}
SHORT_OPTIONS_WITH_VALUE = {"-a", "-C", "-c", "-i", "-m", "-p", "-s"}


@dataclass(frozen=True)
class AutoRoute:
    """Routing decision for one Codex invocation."""

    kind: RouteKind
    subcommand: str | None
    parse_stdout_jsonl: bool = False


def classify_codex_args(args: list[str]) -> AutoRoute:
    """Classify a Codex argv tail for safe automatic tracking."""

    subcommand = first_non_option_arg(args)
    if subcommand in HELP_VERSION_FLAGS:
        return AutoRoute("bypass", subcommand)
    if subcommand in BYPASS_SUBCOMMANDS:
        return AutoRoute("bypass", subcommand)
    if subcommand in PIPE_SUBCOMMANDS:
        if command_help_requested(args):
            return AutoRoute("bypass", subcommand)
        return AutoRoute("pipe", subcommand, parse_stdout_jsonl=args_include_json(args))
    if subcommand in TUI_SUBCOMMANDS:
        return AutoRoute("tui", subcommand)
    return AutoRoute("tui", subcommand)


def first_non_option_arg(args: list[str]) -> str | None:
    """Return the first non-option argument, accounting for common Codex globals."""

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            return None
        if token in HELP_VERSION_FLAGS:
            return token
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            if option in LONG_OPTIONS_WITH_VALUE and "=" not in token:
                index += 2
            else:
                index += 1
            continue
        if token.startswith("-") and token != "-":
            if token in SHORT_OPTIONS_WITH_VALUE:
                index += 2
            else:
                index += 1
            continue
        return token
    return None


def command_help_requested(args: list[str]) -> bool:
    """Return true when a subcommand invocation only asks for help/version."""

    return any(arg in HELP_VERSION_FLAGS for arg in args)


def args_include_json(args: list[str]) -> bool:
    """Return true when Codex stdout is expected to be JSONL."""

    return "--json" in args


def run_auto(args: list[str], address: DaemonAddress, *, real_codex: str | None = None) -> int:
    """Run one Codex invocation through the appropriate collector."""

    resolved_codex = resolve_real_codex(real_codex)
    if not resolved_codex:
        print("codex-speed: could not find the real Codex executable", file=sys.stderr)
        return 127
    if tracking_disabled():
        return exec_direct(resolved_codex, args)

    route = classify_codex_args(args)
    if route.kind == "bypass":
        return exec_direct(resolved_codex, args)

    ensure_daemon(address)
    if route.kind == "pipe":
        return run_pipe_command(
            [resolved_codex, *args],
            address,
            mode="exec",
            parse_stdout_jsonl=route.parse_stdout_jsonl,
        )
    return run_tui(args, address, codex_bin=resolved_codex)


def resolve_real_codex(real_codex: str | None = None) -> str | None:
    """Resolve the executable that the shim should delegate to."""

    if real_codex:
        return real_codex
    return find_real_codex(default_shim_dir())


def tracking_disabled() -> bool:
    """Return true when the current invocation should bypass tracking."""

    value = os.environ.get("CODEX_SPEED_DISABLE", "")
    return value not in {"", "0", "false", "FALSE", "no", "NO"}


def exec_direct(real_codex: str, args: list[str]) -> int:
    """Replace this process with the real Codex process."""

    try:
        os.execv(real_codex, [real_codex, *args])
    except OSError as exc:
        print(f"codex-speed: failed to start Codex: {exc}", file=sys.stderr)
        return 127


def ensure_daemon(address: DaemonAddress) -> None:
    """Start the local daemon if it is not already healthy."""

    if health_check(address):
        return
    if tracking_disabled() or os.environ.get("CODEX_SPEED_NO_DAEMON_START"):
        return

    state_dir = default_state_dir()
    log_path = default_log_path()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("ab", buffering=0)
    except OSError as exc:
        print(f"codex-speed: could not create daemon log at {log_path}: {exc}", file=sys.stderr)
        return

    env = os.environ.copy()
    command = [
        sys.executable,
        "-m",
        "codex_speed",
        "daemon",
        "--listen",
        f"{address.host}:{address.port}",
    ]
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        print(f"codex-speed: failed to start metrics daemon: {exc}", file=sys.stderr)
        return

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if health_check(address):
            return
        time.sleep(0.1)
    print(
        f"codex-speed: metrics daemon did not become healthy; see {Path(log_path)}",
        file=sys.stderr,
    )


def health_check(address: DaemonAddress, *, timeout_seconds: float = 0.25) -> bool:
    """Return true when the daemon health endpoint responds."""

    try:
        with urllib.request.urlopen(f"{address.base_url}/healthz", timeout=timeout_seconds) as resp:
            return 200 <= resp.status < 300
    except (OSError, urllib.error.URLError):
        return False
