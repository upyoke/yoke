"""Tool-shaped ``yoke ui`` — the door to the machine-local universe view.

The view is a daemon, not a terminal job: ``yoke ui up`` starts the
token-gated, read-only server detached and prints the tokened URL,
``yoke ui down`` stops it, and ``yoke ui`` / ``yoke ui status`` report
whether it is serving. The server outlives the shell that started it
and, on macOS, the login session — closing the window no longer closes
the view. The foreground server it supervises is
``yoke ui serve-process``, a child entrypoint rather than an operator
command.

Only ``up`` and the serving child consult the connection allowlist (see
:mod:`yoke_cli.commands.universe_ui_connection`); ``status`` and
``down`` carry no gate, because they report on and stop a process
rather than open a universe.

The tokened URL printed here is the user's door — terminal-only output,
never written into event streams or logs. ``--json`` carries it under
``private_url`` so the secrecy is obvious to tooling.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands import universe_ui_connection as connection
from yoke_cli.commands.universe_ui_connection import UniverseUiError
from yoke_cli.commands.universe_ui_serve import (
    UI_SERVE_PROCESS_USAGE,
    ui_serve_process,
)
from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config.universe_ui_daemon_state import UiDaemonError
from yoke_cli.config.universe_ui_launchd import UiLaunchdError

AdapterFn = Callable[[List[str]], int]

UI_USAGE = "yoke ui [--json]"
UI_UP_USAGE = "yoke ui up [--host HOST] [--port PORT] [--no-browser] [--json]"
UI_DOWN_USAGE = "yoke ui down [--json]"
UI_STATUS_USAGE = "yoke ui status [--json]"

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke ui": UI_USAGE,
    "yoke ui up": UI_UP_USAGE,
    "yoke ui down": UI_DOWN_USAGE,
    "yoke ui status": UI_STATUS_USAGE,
    "yoke ui serve-process": UI_SERVE_PROCESS_USAGE,
}


def ui(args: List[str]) -> int:
    """Bare ``yoke ui`` is the status read; serving is ``yoke ui up``."""
    return ui_status(args, prog="yoke ui", usage=UI_USAGE)


def ui_status(
    args: List[str],
    *,
    prog: str = "yoke ui status",
    usage: str = UI_STATUS_USAGE,
) -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Report whether this machine's universe view is serving, and "
            "print its tokened URL when it is. Reading status is all bare "
            "`yoke ui` does — serving is `yoke ui up`."
        ),
        epilog=(
            "The view is a machine daemon, not a terminal job:\n"
            "  yoke ui up      start it detached and print the tokened URL\n"
            "  yoke ui         report it (this command)\n"
            "  yoke ui status  the same report, named\n"
            "  yoke ui down    stop it and drop its supervisor\n"
            "\nThe URL carries a session token stable to this machine — "
            "treat it like a password. The server binds loopback only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        report = daemon.status()
    except UiDaemonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps({"ok": True, **report}, sort_keys=True), flush=True)
        return 0
    _print_status(report)
    return 0


def ui_up(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui up",
        description=(
            "Start the machine-local universe view as a detached daemon "
            "and print its tokened URL. The server binds loopback only, "
            "reuses this machine's stable session token, and keeps "
            "serving after the terminal closes (on macOS, after a reboot "
            "too). Requires a non-prod local-postgres connection "
            "(`yoke init --local`)."
        ),
    )
    _add_host_port_flags(parser)
    parser.add_argument(
        "--no-browser", dest="no_browser", action="store_true",
        help="Do not open the default browser on the tokened URL.",
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, UI_UP_USAGE)
    if parsed is None:
        return 2

    env_name, refusal = connection.servable_connection()
    if refusal is not None:
        print(f"error: {refusal}", file=sys.stderr)
        return 1

    try:
        report = daemon.status()
        if report.get("running"):
            report = {**report, "started": False}
        else:
            server = connection.ui_server()
            host = server.resolve_ui_host(parsed.host)
            port = server.resolve_ui_port(parsed.port, host=host)
            report = daemon.up(host=host, port=port, env=env_name)
    except (UniverseUiError, UiDaemonError, UiLaunchdError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    url = str(report.get("private_url") or "")
    opened = bool(url) and not parsed.no_browser
    if parsed.json_mode:
        print(json.dumps(
            {"ok": True, "browser_opened": opened, **report}, sort_keys=True,
        ), flush=True)
    else:
        _print_status(report)
        note = str(report.get("supervisor_note") or "")
        if note:
            print(note, flush=True)
    if opened:
        webbrowser.open(url)
    return 0


def ui_down(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui down",
        description=(
            "Stop the machine-local universe view and remove its "
            "supervisor. The machine's session token survives, so the "
            "next `yoke ui up` prints the same URL."
        ),
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, UI_DOWN_USAGE)
    if parsed is None:
        return 2
    try:
        report = daemon.down()
    except (UiDaemonError, UiLaunchdError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps({"ok": True, **report}, sort_keys=True), flush=True)
    elif report.get("stopped"):
        print(f"yoke ui: stopped (pid {report.get('stopped_pid')})")
    else:
        print("yoke ui: already stopped")
    return 0


def _print_status(report: Dict[str, object]) -> None:
    if not report.get("running"):
        print("yoke ui: stopped")
        print("Start the local universe view with `yoke ui up`.", flush=True)
        return
    print(
        "yoke ui: serving the local universe (read-only) as pid "
        f"{report.get('pid')} on env {report.get('env')} at:"
    )
    print(f"  {report.get('private_url')}")
    print("This URL is the door — treat it like a password.")
    if not report.get("serving"):
        print(
            "The process is alive but not yet accepting connections; "
            f"its log is {daemon.log_path()}."
        )
    print("Stop it with `yoke ui down`.", flush=True)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", dest="json_mode", action="store_true",
        help=(
            "Print a JSON line naming the daemon state and, when it is "
            "serving, private_url (the tokened URL — private by "
            "construction)."
        ),
    )


def _add_host_port_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host", default=None,
        help=(
            "Loopback host for the UI server (default: 127.0.0.1; "
            "remote-facing hosts are refused)."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=(
            "TCP port for the UI server (default: the server's canonical "
            "port; refused with guidance when already in use)."
        ),
    )


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("ui",): ui,
    ("ui", "up"): ui_up,
    ("ui", "down"): ui_down,
    ("ui", "status"): ui_status,
    ("ui", "serve-process"): ui_serve_process,
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "UI_DOWN_USAGE",
    "UI_STATUS_USAGE",
    "UI_UP_USAGE",
    "UI_USAGE",
    "UniverseUiError",
    "ui",
    "ui_down",
    "ui_serve_process",
    "ui_status",
    "ui_up",
]
