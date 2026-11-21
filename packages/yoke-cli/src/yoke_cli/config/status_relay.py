"""This machine's relay liveness, read by ``yoke status`` without the engine.

``yoke status`` runs on HTTPS product clients that never import the engine,
so it reads two engine-free facts. A relay that follows served releases runs
from its state directory, so a process scan shows whether it is running; a
local-universe relay runs the machine's installed launcher, which no process
scan can tell apart, so only its heartbeat is judged. The control plane's
relay list shows whether this machine's relay heartbeat is current; it goes
silent within two poll intervals of the relay stopping.

A relay this machine is known to run (its native service document is on
disk, a registered relay row, or a running process) that is not running or
not heartbeating is a ``relay_down`` error, so status never reports ``ok`` with a dead relay. ``yoke relay status`` and
``yoke doctor`` read the native supervisor itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from yoke_cli.config.status_surface_policy import _control_plane_ready

_TIMEOUT_S = 8.0
RELAY_DOWN = "relay_down"
_TASK_RUNNER = "task-runner.py"
_STOPPED_RECOVERY = {
    "win32": "While its Task Scheduler task runs, the task runner restarts the relay "
    "within about a minute; if it stays down, run `yoke relay install` to restart the task.",
    "darwin": "Run `yoke relay install` to reload its launchd login item.",
    "linux": "Run `yoke relay install` to restart its systemd user unit.",
}
_STALE_RECOVERY = (
    "A running relay's supervisor restarts it within about a minute after it "
    "exits; if the heartbeat stays stale, run `yoke relay status` for the "
    "reason, then `yoke relay install`."
)

RelayRows = Callable[[], list[Mapping[str, Any]]]
Processes = Callable[[], Iterable[Any]]


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


def _processes() -> Iterable[Any]:
    from yoke_contracts.platform_process import process_command_lines

    return process_command_lines()


def _service_installed(instance: Any) -> bool:
    """Whether this relay's native service document is on disk.

    Install writes it and uninstall removes it, so it proves an installed
    relay even when the control plane's relay list cannot show this machine.
    """
    if sys.platform == "win32":
        return (Path(instance.state_dir) / _TASK_RUNNER).is_file()
    if sys.platform == "darwin":
        return (Path.home() / "Library/LaunchAgents" / f"{instance.label}.plist").is_file()
    return (Path.home() / ".config/systemd/user" / f"{instance.label}.service").is_file()


def _running_from(state_dir: Path, processes: Processes) -> bool:
    roots = {os.path.normcase(str(path)) for path in (Path(state_dir), Path(state_dir).resolve())}
    for process in processes():
        # The Windows task runner outlives the relay it restarts; it is not the relay.
        if process.pid == os.getpid() or any(Path(str(a)).name == _TASK_RUNNER for a in process.cmdline):
            continue
        for argument in process.cmdline:
            value = os.path.normcase(str(argument))
            if any(value == root or value.startswith(root + os.sep) for root in roots):
                return True
    return False


def _heartbeat(machine_id: str, rows: RelayRows) -> tuple[bool | None, str]:
    """Current, stale, or None when unread or no relay of this machine is registered."""
    try:
        mine = [row for row in rows() if str(row.get("machine_id") or "") == machine_id]
    except Exception as exc:  # noqa: BLE001 - status reports what it could not read
        return None, f"relay heartbeat unread: {exc}"
    for row in mine:
        if row.get("liveness") == "connected":
            return True, str(row.get("last_seen_at") or "")
    return (False, "") if mine else (None, "no relay of this machine is registered")


def attach_relay(
    report: dict[str, Any],
    config_path: Path,
    *,
    explicit_env: str | None = None,
    relay_rows: RelayRows | None = None,
    processes: Processes | None = None,
) -> dict[str, Any]:
    """Attach the relay block, adding ``relay_down`` when it is not live."""
    from yoke_contracts.machine_config.relay_instance import RelayInstanceError, resolve_relay_instance
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    try:
        instance = resolve_relay_instance(config_path=config_path, environment=explicit_env)
    except RelayInstanceError as exc:
        report["relay"] = {"relevant": False, "reason": str(exc)}
        return report
    running: bool | None = None
    if instance.follows_served_release:
        try:
            running = _running_from(instance.state_dir, processes or _processes)
        except Exception:  # noqa: BLE001 - an unreadable process table is not a verdict
            running = None
    machine = read_machine_id(config_path)
    connected, detail = None, "control plane not reachable from this status run"
    if machine and _control_plane_ready(report):
        connected, detail = _heartbeat(machine, relay_rows or _relay_rows)
    block: dict[str, Any] = {
        "relevant": True, "environment": instance.environment,
        "running": running, "heartbeat_current": connected,
    }
    block["last_seen_at" if connected else "heartbeat_reason"] = detail
    report["relay"] = block
    try:
        installed = _service_installed(instance)
    except OSError:
        installed = False
    block["installed"] = installed
    known = installed or running is True or connected is not None
    problems = []
    if known and running is False:
        problems.append("no relay process is running from its state directory")
    if connected is False:
        problems.append("the control plane has no current heartbeat from this machine")
    block["ok"] = False if problems else (True if connected else None)
    if not problems:
        return report
    recovery = _STALE_RECOVERY if running else _STOPPED_RECOVERY.get(sys.platform, "Run `yoke relay install`.")
    report["issues"].append({
        "severity": "error",
        "code": RELAY_DOWN,
        "message": f"the machine relay ({instance.environment}) is down: " + "; ".join(problems),
        "hint": recovery,
    })
    report["ok"] = False
    return report


__all__ = ["RELAY_DOWN", "attach_relay"]
