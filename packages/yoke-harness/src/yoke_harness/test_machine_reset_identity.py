"""Retire the reset user's own Yoke registration before its profile is erased."""

from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from uuid import UUID

from yoke_contracts.machine_authorization import MACHINE_RETIRED
from yoke_contracts.machine_config.paths import DEFAULT_HOME_NAME
from yoke_contracts.machine_config.schema import DEFAULT_CONFIG_NAME, MACHINE_ID_KEY
from yoke_contracts.machine_config.schema_connections import configured_active_env
from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_contracts.test_machine_types import HostActionResult

_RECOVERY = (
    "Repair the test user's Yoke config, launcher or saved connection on this "
    "Test Machine, then retry the reset. The profile has not been wiped."
)


def _failure(reason: str, **details) -> HostActionResult:
    return HostActionResult(
        False,
        {"machine_retirement": {"reason": reason, "recovery": _RECOVERY, **details}},
        "test_machine_identity_retirement_failed",
    )


def retire_reset_identity(control, *, native_windows: bool = False) -> HostActionResult:
    """Read the lab's UUID and retire it using the lab's saved connection."""
    path_type = PureWindowsPath if native_windows else PurePosixPath
    config_path = path_type(control.home) / DEFAULT_HOME_NAME / DEFAULT_CONFIG_NAME
    try:
        document = control.read_remote_text(str(config_path))
    except Exception as exc:
        return _failure("identity_file_read_failed", error_type=type(exc).__name__)
    if document is None:
        return HostActionResult(True, {})

    try:
        config = json.loads(document)
        machine_id = config.get(MACHINE_ID_KEY)
        if machine_id is not None and str(UUID(machine_id)) != machine_id:
            raise ValueError("noncanonical UUID")
    except (AttributeError, TypeError, ValueError):
        return _failure("identity_file_invalid")

    if machine_id is None:
        return HostActionResult(True, {})
    connections = config.get("connections")
    env = configured_active_env(config)
    if not isinstance(connections, dict) or env not in connections:
        return _failure("identity_connection_missing", machine_id=machine_id)

    try:
        result = control.run_command(
            [
                control.path_state.yoke_bin, "--env", env,
                "machine", "retire", machine_id, "--confirm", "--json",
            ],
            required_session_context=GUI_SESSION_CONTEXT if native_windows else None,
            timeout=60,
        )
    except Exception as exc:
        return _failure(
            "retire_command_failed", machine_id=machine_id, error_type=type(exc).__name__
        )
    outcome = "retired"
    if result.returncode:
        try:
            code = json.loads(result.stdout)["error"]["code"]
        except (KeyError, TypeError, ValueError):
            code = None
        if code == MACHINE_RETIRED:
            outcome = "already_retired"
        elif code == "machine_unregistered":
            outcome = "already_absent"
        else:
            reason = (
                code
                if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code)
                else "retire_command_failed"
            )
            return _failure(reason, machine_id=machine_id, exit_code=result.returncode)
    return HostActionResult(
        True, {"machine_retirement": {"machine_id": machine_id, "outcome": outcome}}
    )
