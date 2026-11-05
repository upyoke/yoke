"""Open self-host or machine-local workbenches without exposing sign-in tokens.

``yoke ui up`` opens the browser and starts the local daemon when needed.
``yoke ui`` / ``status`` report daemon state; ``down`` stops it. Browser
admission URLs stay in memory and never enter text or JSON output. Agents,
headless callers and ``--no-browser`` receive the human-terminal recovery.
"""

from __future__ import annotations

from yoke_contracts.timestamps import InvalidInstant

import argparse
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands import universe_ui_connection as connection
from yoke_cli.commands.universe_ui_connection import UniverseUiError
from yoke_cli.commands.universe_ui_remote import self_host_report
from yoke_cli.commands.universe_ui_serve import (
    UI_SERVE_PROCESS_USAGE,
    ui_serve_process,
)
from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config.hosted_machine_browser import open_url
from yoke_cli.config.browser_admission import browser_recovery, open_private_url
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
    "yoke ui restart-running": "yoke ui restart-running [--json]",
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
            "Report whether this machine's web dashboard is serving, and "
            "report its state without sign-in tokens. Reading status is all bare "
            "`yoke ui` does — serving is `yoke ui up`."
        ),
        epilog=(
            "The web dashboard is a machine daemon, not a terminal job:\n"
            "  yoke ui up      start it detached and open the browser\n"
            "  yoke ui         report it (this command)\n"
            "  yoke ui status  the same report, named\n"
            "  yoke ui down    stop it and drop its supervisor\n"
            "\nRun `yoke ui up` from your own terminal to sign in. "
            "The server binds loopback only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        report = daemon.status()
    except (UiDaemonError, InvalidInstant) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        report.pop("private_url", None)
        print(json.dumps({"ok": True, **report}, sort_keys=True), flush=True)
        return 0
    _print_status(report)
    return 0


def ui_restart_running(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui restart-running",
        description=(
            "Restart an existing machine dashboard after package installation, "
            "keeping its environment, host, port and bookmark. A stopped dashboard "
            "stays stopped; no browser opens. The public installer runs this step."
        ),
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, "yoke ui restart-running [--json]")
    if parsed is None:
        return 2
    try:
        report = daemon.restart_running()
    except (UiDaemonError, UiLaunchdError, InvalidInstant, OSError) as exc:
        print(
            f"ui_restart_failed: {exc}; rerun the installer after recovery.",
            file=sys.stderr,
        )
        return 1
    if parsed.json_mode:
        print(json.dumps({"ok": True, **report}, sort_keys=True), flush=True)
    elif report["restarted"]:
        print("Restarted the running dashboard with the installed Yoke version.")
    return 0


def ui_up(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui up",
        description=(
            "Open the active self-host server's web dashboard, using company "
            "sign-in or a single-use API-token sign-in link. On a non-prod "
            "local-postgres connection (`yoke init --local`), start the "
            "loopback web dashboard as a detached daemon and open the browser."
        ),
    )
    _add_host_port_flags(parser)
    parser.add_argument(
        "--no-browser",
        dest="no_browser",
        action="store_true",
        help="Skip browser opening; sign-in tokens are still never printed.",
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, UI_UP_USAGE)
    if parsed is None:
        return 2

    try:
        report = self_host_report(host=parsed.host, port=parsed.port)
        if report is None:
            env_name, refusal = connection.servable_connection()
            if refusal is not None:
                raise UniverseUiError(refusal)
            report = daemon.status()
            if report.get("running"):
                report = {**report, "started": False}
            else:
                server = connection.ui_server()
                host = server.resolve_ui_host(parsed.host)
                port = server.resolve_ui_port(parsed.port, host=host)
                report = daemon.up(host=host, port=port, env=env_name)
    except (
        UniverseUiError,
        UiDaemonError,
        UiLaunchdError,
        RuntimeError,
        InvalidInstant,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    url = str(report.pop("private_url", "") or "")
    browser = open_private_url(url, disabled=parsed.no_browser, opener=open_url)
    opened = browser.opened
    reason = browser.reason or ""
    recovery = browser_recovery("yoke ui up")
    failed = reason == "browser_open_failed"
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "ok": not failed,
                    "browser_opened": opened,
                    **report,
                    **(
                        {"browser_reason": reason, "recovery": recovery}
                        if reason
                        else {}
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    else:
        if report.get("mode") == "self-host":
            print(
                f"yoke ui: self-host workbench on env {report.get('env')}", flush=True
            )
        else:
            _print_status(report)
        if opened:
            print("Browser opened for sign-in.", flush=True)
        if reason:
            print(f"{reason}: {recovery}", flush=True)
        note = str(report.get("supervisor_note") or "")
        if note:
            print(note, flush=True)
    return 1 if failed else 0


def ui_down(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ui down",
        description=(
            "Stop the machine-local web dashboard and remove its "
            "supervisor. The machine's session token survives, so the "
            "next `yoke ui up` opens the browser for sign-in."
        ),
    )
    _add_json_flag(parser)
    parsed = parse_or_usage_error(parser, args, UI_DOWN_USAGE)
    if parsed is None:
        return 2
    try:
        report = daemon.down()
    except (UiDaemonError, UiLaunchdError, InvalidInstant) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        report.pop("private_url", None)
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
        "yoke ui: serving the local universe as pid "
        f"{report.get('pid')} on env {report.get('env')}"
    )
    print("Run `yoke ui up` from your own terminal to open the browser and sign in.")
    if not report.get("serving"):
        print(
            "The process is alive but not yet accepting connections; "
            f"its log is {daemon.log_path()}."
        )
    print("Stop it with `yoke ui down`.", flush=True)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help=(
            "Print daemon state or self-host browser outcome as JSON. "
            "Sign-in URLs and tokens are never included."
        ),
    )


def _add_host_port_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "Loopback host for the UI server (default: 127.0.0.1; "
            "remote-facing hosts are refused)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
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
    ("ui", "restart-running"): ui_restart_running,
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
