"""Machine-local CLI lifecycle for the one-shot fleet relay."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib
import json
import sys
from typing import Any, Callable, List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.session_control_launch_output import (
    write_relay_summary,
)


RELAY_INSTALL_USAGE = "yoke relay install [--json]"
RELAY_UNINSTALL_USAGE = "yoke relay uninstall [--json]"
RELAY_STATUS_USAGE = "yoke relay status [--json]"
RELAY_SERVE_ONCE_USAGE = "yoke relay serve-once [--json]"


def _plist_operation(action: str) -> Any:
    module = importlib.import_module("yoke_core.tools.session_relay_plist")

    operation: dict[str, Callable[[], Any]] = {
        "install": module.install_relay_launchd,
        "status": module.relay_launchd_status,
        "uninstall": module.uninstall_relay_launchd,
    }
    return operation[action]()


def _serve_once() -> Any:
    from yoke_harness.session_relay import serve_once

    return serve_once()


def _parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    return parser


def _emit(payload: dict[str, Any], *, json_mode: bool, title: str) -> None:
    if json_mode:
        print(json.dumps(payload, sort_keys=True))
        return
    write_relay_summary(payload, sys.stdout, title=title)


def _relay_lifecycle(args: List[str], action: str) -> int:
    usage = {
        "install": RELAY_INSTALL_USAGE,
        "status": RELAY_STATUS_USAGE,
        "uninstall": RELAY_UNINSTALL_USAGE,
    }[action]
    parsed = parse_or_usage_error(
        _parser(f"yoke relay {action}", usage),
        args,
        usage,
    )
    if parsed is None:
        return 2
    try:
        status = _plist_operation(action)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_lifecycle_failed",
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    payload = {
        "supported": bool(status.supported),
        "plist_present": bool(status.plist_present),
        "plist_current": bool(status.plist_current),
        "loaded": bool(status.loaded),
        "plist_path": str(status.plist_path),
    }
    _emit(payload, json_mode=parsed.json_mode, title=f"RELAY {action.upper()}")
    return 0 if status.supported else 1


def relay_install(args: List[str]) -> int:
    return _relay_lifecycle(args, "install")


def relay_uninstall(args: List[str]) -> int:
    return _relay_lifecycle(args, "uninstall")


def relay_status(args: List[str]) -> int:
    return _relay_lifecycle(args, "status")


def relay_serve_once(args: List[str]) -> int:
    parsed = parse_or_usage_error(
        _parser("yoke relay serve-once", RELAY_SERVE_ONCE_USAGE),
        args,
        RELAY_SERVE_ONCE_USAGE,
    )
    if parsed is None:
        return 2
    try:
        outcome = _serve_once()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_serve_failed",
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    payload = asdict(outcome)
    _emit(payload, json_mode=parsed.json_mode, title="RELAY POLL")
    return 1 if str(payload.get("state") or "").endswith("_failed") else 0


__all__ = [
    "RELAY_INSTALL_USAGE",
    "RELAY_SERVE_ONCE_USAGE",
    "RELAY_STATUS_USAGE",
    "RELAY_UNINSTALL_USAGE",
    "relay_install",
    "relay_serve_once",
    "relay_status",
    "relay_uninstall",
]
