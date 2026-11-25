"""Attempt retirement of the reset user's registration through its saved authority."""

from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from uuid import UUID

from yoke_contracts.machine_authorization import MACHINE_RETIRED
from yoke_contracts.machine_config.paths import DEFAULT_HOME_NAME
from yoke_contracts.machine_config.schema import DEFAULT_CONFIG_NAME, MACHINE_ID_KEY
from yoke_contracts.machine_config.schema_connection_validation import validate_connection
from yoke_contracts.machine_config.schema_connections import configured_active_env
from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_contracts.test_machine_types import HostActionResult

_RECOVERY = (
    "Investigate the registry entry only through its verified original authority. "
    "The baseline reset proceeds independently of machine retirement."
)


def _advisory(outcome: str, reason: str, **details) -> HostActionResult:
    return HostActionResult(
        False,
        {"machine_retirement": {
            "outcome": outcome, "reason": reason, "recovery": _RECOVERY, **details,
        }},
        "test_machine_identity_retirement_failed",
    )


def retire_reset_identity(control, *, native_windows: bool = False) -> HostActionResult:
    """Read the lab's UUID and retire it using the lab's saved connection."""
    path_type = PureWindowsPath if native_windows else PurePosixPath
    try:
        config_path = path_type(control.home) / DEFAULT_HOME_NAME / DEFAULT_CONFIG_NAME
        document = control.read_remote_text(str(config_path))
    except Exception as exc:
        return _advisory("skipped", "identity_file_read_failed", error_type=type(exc).__name__)
    if document is None:
        return HostActionResult(True, {})

    try:
        config = json.loads(document)
        machine_id = config.get(MACHINE_ID_KEY)
        if machine_id is not None and str(UUID(machine_id)) != machine_id:
            raise ValueError("noncanonical UUID")
    except (AttributeError, TypeError, ValueError):
        return _advisory("skipped", "identity_file_invalid")

    if machine_id is None:
        return HostActionResult(True, {})
    connections = config.get("connections")
    env = configured_active_env(config)
    if not env or not isinstance(connections, dict) or env not in connections:
        return _advisory("skipped", "identity_connection_missing", machine_id=machine_id)
    connection = connections[env]
    if not isinstance(connection, dict) or any(
        issue.severity == "error" for issue in validate_connection(env, connection)
    ):
        return _advisory("skipped", "identity_connection_invalid", machine_id=machine_id)

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
        return _advisory(
            "failed", "retire_command_failed", machine_id=machine_id, error_type=type(exc).__name__
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
            return _advisory("failed", reason, machine_id=machine_id, exit_code=result.returncode)
    return HostActionResult(
        True, {"machine_retirement": {"machine_id": machine_id, "outcome": outcome}}
    )
