"""Select the native user supervisor for the standing machine relay."""

from __future__ import annotations

import sys
from yoke_contracts.machine_config.relay_instance import RELAY_LOGOUT_BEHAVIOR
from typing import Any

from yoke_core.tools import session_relay_plist, session_relay_systemd, session_relay_task_scheduler
from yoke_core.domain.relay_launchd_status import RelayInstallError


def relay_service_operation(action: str, **kwargs: Any) -> Any:
    if sys.platform == "linux":
        operations = {
            "install": session_relay_systemd.install_relay_systemd,
            "status": session_relay_systemd.relay_systemd_status,
            "uninstall": session_relay_systemd.uninstall_relay_systemd,
        }
    elif sys.platform == "darwin":
        operations = {
            "install": session_relay_plist.install_relay_launchd,
            "status": session_relay_plist.relay_launchd_status,
            "uninstall": session_relay_plist.uninstall_relay_launchd,
        }
    elif sys.platform == "win32":
        operations = {
            "install": session_relay_task_scheduler.install_relay_task,
            "status": session_relay_task_scheduler.relay_task_status,
            "uninstall": session_relay_task_scheduler.uninstall_relay_task,
        }
    else:
        raise RelayInstallError(
            f"relay_os_unsupported: no relay supervisor for {sys.platform}. "
            "Recovery: run the relay on an OS with a declared supervisor.",
            code="relay_os_unsupported",
        )
    return operations[action](**kwargs)


def relay_service_current(status: Any) -> bool:
    if isinstance(status, session_relay_task_scheduler.RelayTaskStatus):
        return bool(status.task_present and status.task_current and not status.reason)
    if isinstance(status, session_relay_systemd.RelaySystemdStatus):
        return bool(
            status.unit_present
            and status.unit_current
            and status.enabled
            and not status.reason
        )
    return bool(status.plist_present and status.plist_current)


def relay_service_present(status: Any) -> bool:
    if isinstance(status, session_relay_task_scheduler.RelayTaskStatus):
        return status.task_present
    if isinstance(status, session_relay_systemd.RelaySystemdStatus):
        return status.unit_present
    return bool(status.plist_present)


def relay_service_payload(status: Any) -> dict[str, Any]:
    if isinstance(status, session_relay_task_scheduler.RelayTaskStatus):
        document = {
            "supervisor": "Task Scheduler",
            "task_name": status.task_name,
            "task_present": status.task_present,
            "task_current": status.task_current,
            "supervision_reason": status.reason or None,
            "logout_behavior": session_relay_task_scheduler.LOGIN_BEHAVIOR,
        }
    elif isinstance(status, session_relay_systemd.RelaySystemdStatus):
        document = {
            "supervisor": "systemd --user",
            "unit_name": status.unit_path.name,
            "unit_present": status.unit_present,
            "unit_current": status.unit_current,
            "enabled": status.enabled,
            "unit_path": str(status.unit_path),
            "supervision_reason": status.reason or None,
            "logout_behavior": RELAY_LOGOUT_BEHAVIOR if not status.reason else None,
        }
    else:
        document = {
            "launchd_label": str(status.label),
            "plist_present": bool(status.plist_present),
            "plist_current": bool(status.plist_current),
            "plist_path": str(status.plist_path),
        }
    return {
        "supported": bool(status.supported),
        "environment": str(status.environment),
        "loaded": bool(status.loaded),
        "state_dir": str(status.state_dir) if status.state_dir else None,
        **document,
    }
