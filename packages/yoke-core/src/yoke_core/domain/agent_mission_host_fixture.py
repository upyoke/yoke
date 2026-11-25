"""Native Windows walker access: machine fixtures, an elevated shell, a second user.

``yoke qa mission host-command`` reaches these through the walk's lease like
every host command. Each runs on native Windows only and refuses by name
elsewhere; the fixture library and the SYSTEM runner live with the Windows
control.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.machine_qa_result_safety import redact_machine_qa_value

WINDOWS_ONLY = "native_windows_flag_os_unsupported"


def require_native_windows(settings: dict[str, Any], flag: str) -> None:
    """Refuse a Windows-only flag on another OS before touching the host."""
    os_name = settings.get("os")
    if os_name != "windows":
        raise HostControlLocalError(
            code=WINDOWS_ONLY,
            phase="host_command",
            detail=f"{flag} runs on native Windows Test Machines only; this one is {os_name}.",
            recovery_hint=f"Drop {flag}, or select a native Windows Test Machine with --test-machine.",
        )


def windows_host_variant(execution: Any, *, elevated: bool, second_user: bool) -> Any:
    """The control a walker command runs on: the lease's own, or a Windows variant."""
    if not (elevated or second_user):
        return execution.control
    settings = execution.material.settings
    for flag, chosen in (("--elevated", elevated), ("--second-user", second_user)):
        if chosen:
            require_native_windows(settings, flag)
    if elevated and second_user:
        raise HostControlLocalError(
            code="native_windows_flags_conflict",
            phase="host_command",
            detail="--elevated and --second-user name different Windows accounts.",
            recovery_hint="Pass one of them; the second user is never an administrator.",
        )
    return execution.control.variant(elevated=elevated, second_user=second_user)


def execute_agent_mission_host_fixture(
    raw_contract: dict[str, Any], *, name: str, undo: bool
) -> dict[str, Any]:
    """Apply or undo one machine-wide fixture as SYSTEM and return its verify records."""
    from yoke_core.domain.host_control_runner import resolve_contract_host_control
    from yoke_core.domain.machine_qa_execution_contract import (
        HostControlExecutionContract,
    )

    contract = HostControlExecutionContract.model_validate(raw_contract)
    require_native_windows(contract.settings, "--fixture")
    control, material = resolve_contract_host_control(
        {"project_id": contract.project_id, "project": contract.project, "settings": contract.settings}
    )
    records = control.machine_fixture(name, undo=undo)
    result = {
        "exit_code": 0,
        "fixture": name,
        "operation": "undo" if undo else "setup",
        "verify_records": records,
        "execution_context": "system",
    }
    return redact_machine_qa_value(result, tuple(material.secrets.values()))


__all__ = [
    "WINDOWS_ONLY",
    "execute_agent_mission_host_fixture",
    "require_native_windows",
    "windows_host_variant",
]
