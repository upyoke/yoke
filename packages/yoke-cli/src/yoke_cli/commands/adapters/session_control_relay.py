"""Machine-local CLI lifecycle for the one-shot fleet relay."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib
import json
import sys
from typing import Any, Callable, List
from uuid import UUID

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.commands.adapters.session_control_launch_output import (
    write_relay_probe_summary,
    write_relay_summary,
)
from yoke_contracts.session_control.teaching import FLEET_OWNERSHIP_GUIDANCE
from yoke_contracts.session_execution import is_subagent_execution


RELAY_INSTALL_USAGE = "yoke relay install [--json]"
RELAY_UNINSTALL_USAGE = "yoke relay uninstall [--json]"
RELAY_STATUS_USAGE = "yoke relay status [--json]"
RELAY_SERVE_ONCE_USAGE = (
    "yoke relay serve-once [--broker --broker-lease LEASE_ID] [--json]"
)
RELAY_DIAGNOSTIC_USAGE = "yoke relay diagnostic <opaque-ref>"
RELAY_PROBE_SURFACE_USAGE = "yoke relay probe-surface [--surface S] [--json]"


def _plist_operation(action: str) -> Any:
    module = importlib.import_module("yoke_core.tools.session_relay_plist")

    operation: dict[str, Callable[[], Any]] = {
        "install": module.install_relay_launchd,
        "status": module.relay_launchd_status,
        "uninstall": module.uninstall_relay_launchd,
    }
    return operation[action]()


def _contain_stranded_natives() -> None:
    """Terminate unsupervised launches and inactive detached resumes.

    The relay owns machine-local custody, so the sweep runs on its cadence
    rather than waiting for an operator to notice an uncontrolled native.
    """
    from yoke_harness.session_launch_containment import (
        contain_stranded_launch_natives,
    )

    for outcome in contain_stranded_launch_natives():
        print(
            f"contained supervised native: kind={outcome.supervision_kind} "
            f"id={outcome.launch_id} pid={outcome.pid} result={outcome.result} "
            f"reason={outcome.reason}",
            file=sys.stderr,
        )


def _serve_once(
    *, broker_only: bool = False, broker_lease_id: str | None = None
) -> Any:
    from yoke_harness.session_relay import serve_once
    from yoke_harness.session_relay_inventory import collect_cached_inventory
    from yoke_harness.session_relay_surface_probe_cache import (
        refresh_surface_probe_cache,
    )

    _contain_stranded_natives()
    return serve_once(
        inventory_provider=collect_cached_inventory,
        inventory_refresher=(None if broker_only else refresh_surface_probe_cache),
        broker_only=broker_only,
        broker_lease_id=broker_lease_id,
    )


def _read_diagnostic(reference: str) -> bytes:
    from yoke_harness.session_relay_native_diagnostics import (
        read_native_diagnostic,
    )

    return read_native_diagnostic(reference)


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
        "environment": str(status.environment),
        "launchd_label": str(status.label),
        "plist_present": bool(status.plist_present),
        "plist_current": bool(status.plist_current),
        "loaded": bool(status.loaded),
        "plist_path": str(status.plist_path),
        "state_dir": str(status.state_dir) if status.state_dir else None,
    }
    _emit(payload, json_mode=parsed.json_mode, title=f"RELAY {action.upper()}")
    if not status.supported:
        return 1
    if action == "status" and not (
        status.plist_present and status.plist_current and status.loaded
    ):
        return 1
    return 0


def relay_install(args: List[str]) -> int:
    return _relay_lifecycle(args, "install")


def relay_uninstall(args: List[str]) -> int:
    return _relay_lifecycle(args, "uninstall")


def relay_status(args: List[str]) -> int:
    return _relay_lifecycle(args, "status")


def relay_serve_once(args: List[str]) -> int:
    parser = _parser("yoke relay serve-once", RELAY_SERVE_ONCE_USAGE)
    parser.add_argument(
        "--broker",
        action="store_true",
        help="bypass local cadence and claim only a reserved peer wake",
    )
    parser.add_argument(
        "--broker-lease",
        help="claim only this exact peer-wake reservation",
    )
    parsed = parse_or_usage_error(
        parser,
        args,
        RELAY_SERVE_ONCE_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.broker != bool(parsed.broker_lease):
        return usage_error("--broker and --broker-lease must be provided together")
    broker_lease_id = None
    if parsed.broker_lease:
        try:
            broker_lease_id = str(UUID(parsed.broker_lease))
        except (TypeError, ValueError, AttributeError):
            return usage_error("--broker-lease must be a UUID")
    if is_subagent_execution():
        return usage_error(FLEET_OWNERSHIP_GUIDANCE)
    try:
        outcome = _serve_once(
            broker_only=parsed.broker,
            broker_lease_id=broker_lease_id,
        )
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
    # A reported native failure is a settled relay transaction, not a request to
    # rerun the native action. Only a failed control-plane boundary exits nonzero.
    return 1 if str(payload.get("state") or "").endswith("_failed") else 0


def relay_probe_surface(args: List[str]) -> int:
    from yoke_harness.session_relay_surface_probe_cache import (
        refresh_surface_probe_cache,
    )
    from yoke_harness.session_relay_surface_probes import KNOWN_SURFACE_PROBES

    parser = _parser("yoke relay probe-surface", RELAY_PROBE_SURFACE_USAGE)
    parser.add_argument("--surface", choices=KNOWN_SURFACE_PROBES)
    parsed = parse_or_usage_error(parser, args, RELAY_PROBE_SURFACE_USAGE)
    if parsed is None:
        return 2
    try:
        probes = refresh_surface_probe_cache(parsed.surface)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_surface_probe_failed",
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    payload = {"count": len(probes), "probes": list(probes)}
    if parsed.json_mode:
        print(json.dumps(payload, sort_keys=True))
    else:
        write_relay_probe_summary(payload, sys.stdout)
    return 0 if all(probe.get("verdict") == "ok" for probe in probes) else 1


def relay_diagnostic(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke relay diagnostic",
        description=(
            "Read one machine-user-local native failure capture by opaque reference."
        ),
    )
    parser.add_argument("reference")
    parsed = parse_or_usage_error(parser, args, RELAY_DIAGNOSTIC_USAGE)
    if parsed is None:
        return 2
    try:
        payload = _read_diagnostic(parsed.reference)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_diagnostic_unavailable",
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    sys.stdout.buffer.write(payload)
    if payload and not payload.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")
    return 0


__all__ = [
    "RELAY_DIAGNOSTIC_USAGE",
    "RELAY_INSTALL_USAGE",
    "RELAY_PROBE_SURFACE_USAGE",
    "RELAY_SERVE_ONCE_USAGE",
    "RELAY_STATUS_USAGE",
    "RELAY_UNINSTALL_USAGE",
    "relay_diagnostic",
    "relay_install",
    "relay_probe_surface",
    "relay_serve_once",
    "relay_status",
    "relay_uninstall",
]
