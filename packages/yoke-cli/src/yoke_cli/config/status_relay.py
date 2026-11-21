"""This machine's relay liveness, read by ``yoke status``.

An installed relay whose supervisor is not running it, or whose control-plane
heartbeat is not current, is a ``relay_down`` error, so status never reports
``ok`` with a dead relay. A machine with no installed relay, or a supervisor
that cannot be read, is reported without judging it: setup and
``yoke doctor`` own installation and supervisor policy.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config.status_surface_policy import _control_plane_ready

_TIMEOUT_S = 8.0
RELAY_DOWN = "relay_down"
_STOPPED_RECOVERY = {
    "win32": "Run `yoke relay install` to restart its Task Scheduler task now; "
    "otherwise it starts at the next logon.",
    "darwin": "Run `yoke relay install` to reload its launchd login item.",
    "linux": "Run `yoke relay install` to restart its systemd user unit.",
}
_STALE_RECOVERY = (
    "Its supervisor restarts an exited relay within about a minute; if the "
    "heartbeat stays stale, run `yoke relay status` for the reason, then "
    "`yoke relay install`."
)

RelayRows = Callable[[], list[Mapping[str, Any]]]


def _service_status(instance: Any) -> Any:
    service = importlib.import_module("yoke_core.tools.session_relay_service")
    status = service.relay_service_operation("status", instance=instance)
    return status, bool(service.relay_service_present(status))


def _relay_rows() -> list[Mapping[str, Any]]:
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_contracts.api.function_call import TargetRef
    from yoke_contracts.session_control.function_ids import RELAY_LIST_FUNCTION_ID

    response = call_dispatcher(
        function_id=RELAY_LIST_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"state": "active", "limit": 500},
        timeout_s=_TIMEOUT_S,
    )
    result = getattr(response, "result", None)
    rows = result.get("relays") if isinstance(result, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("the relay list returned no relays")
    return [row for row in rows if isinstance(row, Mapping)]


def _heartbeat(machine_id: str, rows: RelayRows) -> tuple[bool | None, str]:
    """Whether this machine's relay heartbeat is current; None when unread."""
    try:
        listed = rows()
    except Exception as exc:  # noqa: BLE001 - status reports what it could not read
        return None, f"relay heartbeat unread: {exc}"
    for row in listed:
        if str(row.get("machine_id") or "") == machine_id and row.get("liveness") == "connected":
            return True, str(row.get("last_seen_at") or "")
    return False, ""


def attach_relay(
    report: dict[str, Any],
    config_path: Path,
    *,
    explicit_env: str | None = None,
    service_status: Callable[[Any], tuple[Any, bool]] | None = None,
    relay_rows: RelayRows | None = None,
) -> dict[str, Any]:
    """Attach the relay block, adding ``relay_down`` when it is not live."""
    service_status = service_status or _service_status
    relay_rows = relay_rows or _relay_rows
    from yoke_contracts.machine_config.relay_instance import (
        RelayInstanceError,
        resolve_relay_instance,
    )
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    try:
        instance = resolve_relay_instance(config_path=config_path, environment=explicit_env)
    except RelayInstanceError as exc:
        report["relay"] = {"relevant": False, "reason": str(exc)}
        return report
    block: dict[str, Any] = {"relevant": True, "environment": instance.environment}
    report["relay"] = block
    try:
        status, installed = service_status(instance)
    except Exception as exc:  # noqa: BLE001 - an unreadable supervisor is reported, not judged
        block.update(ok=None, reason=f"relay supervisor unread: {exc}")
        return report
    if not status.supported or not installed:
        block.update(installed=installed, ok=None,
                     reason=getattr(status, "reason", "") or ("" if installed else "relay is not installed"))
        return report
    running = bool(status.loaded)
    machine = read_machine_id(config_path)
    connected, detail = (None, "control plane not reachable from this status run")
    if machine and _control_plane_ready(report):
        connected, detail = _heartbeat(machine, relay_rows)
    block.update(installed=True, running=running, heartbeat_current=connected)
    if connected:
        block["last_seen_at"] = detail
    elif detail:
        block["heartbeat_reason"] = detail
    problems = [] if running else ["its supervisor is not running it"]
    if connected is False:
        problems.append("the control plane has no current heartbeat from this machine")
    block["ok"] = not problems and (None if connected is None else True)
    if problems:
        recovery = _STOPPED_RECOVERY.get(sys.platform, "Run `yoke relay install`.") if not running else _STALE_RECOVERY
        report["issues"].append({
            "severity": "error",
            "code": RELAY_DOWN,
            "message": f"the machine relay ({instance.environment}) is down: " + "; ".join(problems),
            "hint": recovery,
        })
        report["ok"] = False
    return report


__all__ = ["RELAY_DOWN", "attach_relay"]
