"""Command line interface for codex-speed."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codex_speed import __version__
from codex_speed.auto_runner import run_auto
from codex_speed.daemon import run_daemon
from codex_speed.events import DaemonAddress
from codex_speed.exec_runner import run_exec
from codex_speed.notifier_agent import send_test_notification
from codex_speed.session_focus import focus_session
from codex_speed.shim import install_shim, uninstall_shim
from codex_speed.tui_runner import run_tui

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9467
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DAEMON_BIND_HOSTS = LOOPBACK_HOSTS | {"0.0.0.0"}


def parse_listen(value: str) -> DaemonAddress:
    """Parse a loopback ``HOST:PORT`` client daemon address."""

    return _parse_address(value, LOOPBACK_HOSTS, "listen address must be loopback")


def parse_daemon_bind(value: str) -> DaemonAddress:
    """Parse a daemon bind address."""

    return _parse_address(
        value,
        DAEMON_BIND_HOSTS,
        "daemon listen address must be loopback or 0.0.0.0",
    )


def _parse_address(
    value: str,
    allowed_hosts: set[str],
    host_error_message: str,
) -> DaemonAddress:
    """Parse ``HOST:PORT`` into a daemon address."""

    if ":" not in value:
        raise argparse.ArgumentTypeError("expected HOST:PORT")
    host, port_text = value.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    if host not in allowed_hosts:
        raise argparse.ArgumentTypeError(host_error_message)
    return DaemonAddress(host=host, port=port)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""

    parser = argparse.ArgumentParser(
        prog="codex-speed",
        description="Monitor local Codex CLI I/O speed and expose Prometheus metrics.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--daemon",
        type=parse_listen,
        default=DaemonAddress(DEFAULT_HOST, DEFAULT_PORT),
        metavar="HOST:PORT",
        help=f"metrics daemon address for wrapper events (default: {DEFAULT_HOST}:{DEFAULT_PORT})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon_parser = subparsers.add_parser("daemon", help="run the local Prometheus daemon")
    daemon_parser.add_argument(
        "--listen",
        type=parse_daemon_bind,
        default=DaemonAddress(DEFAULT_HOST, DEFAULT_PORT),
        metavar="HOST:PORT",
        help=(
            f"daemon bind address; use 0.0.0.0 in containers "
            f"(default: {DEFAULT_HOST}:{DEFAULT_PORT})"
        ),
    )

    subparsers.add_parser("notify-test", help="send a desktop notification test")

    focus_parser = subparsers.add_parser(
        "focus-session",
        help="focus the terminal associated with a tracked session",
    )
    focus_parser.add_argument("session", help="codex-speed session id")
    focus_parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress status output; useful for notification click callbacks",
    )

    exec_parser = subparsers.add_parser("exec", help="run codex exec --json and collect metrics")
    exec_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="arguments for codex exec; prefix with -- to pass Codex options",
    )

    auto_parser = subparsers.add_parser("auto", help="route one codex invocation through safe collectors")
    auto_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="arguments originally passed to codex; prefix with -- to keep leading options",
    )

    tui_parser = subparsers.add_parser("tui", help="run interactive codex through a PTY")
    tui_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="arguments for codex; prefix with -- to pass Codex options",
    )
    install_parser = subparsers.add_parser("install-shim", help="install the PATH shim for codex")
    install_parser.add_argument(
        "--real-codex",
        help="path to the real codex executable; default: first non-shim codex on PATH",
    )
    install_parser.add_argument(
        "--shim-dir",
        type=Path,
        help="directory for the shim (default: ~/.codex-speed/bin)",
    )

    uninstall_parser = subparsers.add_parser("uninstall-shim", help="remove the PATH shim for codex")
    uninstall_parser.add_argument(
        "--shim-dir",
        type=Path,
        help="directory containing the shim (default: ~/.codex-speed/bin)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "daemon":
        run_daemon(args.listen.host, args.listen.port)
        return
    if args.command == "notify-test":
        send_test_notification()
        return
    if args.command == "focus-session":
        result = focus_session(args.session)
        if not args.quiet:
            stream = sys.stdout if result.focused else sys.stderr
            print(result.detail, file=stream)
        raise SystemExit(0 if result.focused else 1)
    daemon_address: DaemonAddress = args.daemon
    if args.command == "install-shim":
        try:
            shim_path = install_shim(real_codex=args.real_codex, shim_dir=args.shim_dir)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"codex-speed: failed to install shim: {exc}\n")
        print(f"Installed Codex shim: {shim_path}")
        print("Add this near the top of your shell config, before the real Codex directory:")
        print('  export PATH="$HOME/.codex-speed/bin:$PATH"')
        print("Then restart the shell or run: hash -r")
        print("Verify with: command -v codex")
        return
    if args.command == "uninstall-shim":
        removed = uninstall_shim(shim_dir=args.shim_dir)
        if removed:
            print("Removed Codex shim.")
        else:
            print("Codex shim was not installed.")
        return
    codex_args = _strip_separator(args.codex_args)
    if args.command == "exec":
        raise SystemExit(run_exec(codex_args, daemon_address))
    if args.command == "auto":
        raise SystemExit(run_auto(codex_args, daemon_address))
    if args.command == "tui":
        raise SystemExit(run_tui(codex_args, daemon_address))
    parser.error("unknown command")


def _strip_separator(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


if __name__ == "__main__":
    main(sys.argv[1:])
