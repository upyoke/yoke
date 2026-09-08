"""Register this machine at connect time and store its rotated credential.

Both connect-time paths call this: ``yoke onboard`` registers at the end of
Apply, once the connection is verified and the relay is installed and the plane
is demonstrably answering. Status only reads registration; registration is an
explicit connect or reconnect action.

Registration rotates the machine-bound bearer, and a refusal is returned as a reason
rather than raised: connecting a machine should not fail because the registry
disagreed, but the operator must be told which recovery to run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


REGISTER_TIMEOUT_S = 10.0
# One attempt, because the caller's own answer to a refusal is "report it and
# carry on". A control plane that can only be inventoried answers a function
# call 5xx, and the relay reads 5xx as a box worth waiting for: the full ladder
# then spends 94 seconds of backoff inside a connect-time command that had
# nothing to gain from any of them.
REGISTER_ATTEMPTS = 1
# The one command that registers a machine by hand, named by every surface
# that reports a refusal.
REGISTER_RECOVERY_COMMAND = "yoke machine register"


def register_this_machine(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Register this host, returning what the registry now holds for it."""
    from yoke_contracts.machine_config.machine_name import machine_display_name
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    machine = read_machine_id(config_path)
    if not machine:
        return {
            "machine_id": None,
            "registered": False,
            "reason": "machine config has no canonical machine id",
        }
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="machine.register",
            target=TargetRef(kind="global"),
            payload={
                "machine_id": machine,
                "name": machine_display_name(),
            },
            timeout_s=REGISTER_TIMEOUT_S,
            max_attempts=REGISTER_ATTEMPTS,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"machine_id": machine, "registered": False, "reason": str(exc)}
    if not getattr(response, "success", False):
        return {
            "machine_id": machine,
            "registered": False,
            "reason": error_text(getattr(response, "error", None)),
        }
    result = getattr(response, "result", None) or {}
    record = result.get("machine") or {}
    persisted = _persist_credential(result, config_path)
    if persisted is not None:
        return {"machine_id": machine, "registered": False, "reason": persisted}
    return {
        "machine_id": machine,
        "registered": True,
        "name": record.get("name"),
        "owner_actor_id": record.get("owner_actor_id"),
        "access": record.get("access"),
    }


def show_this_machine(config_path: str | Path | None = None) -> dict[str, Any]:
    """Read this host's durable registration without rotating credentials."""
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    machine = read_machine_id(config_path)
    if not machine:
        return {
            "machine_id": None,
            "registered": False,
            "reason": "machine config has no canonical machine id",
        }
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="machine.show",
            target=TargetRef(kind="global"),
            payload={"machine_id": machine},
            timeout_s=REGISTER_TIMEOUT_S,
            max_attempts=REGISTER_ATTEMPTS,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"machine_id": machine, "registered": False, "reason": str(exc)}
    if not getattr(response, "success", False):
        return {
            "machine_id": machine,
            "registered": False,
            "reason": error_text(getattr(response, "error", None)),
        }
    record = (getattr(response, "result", None) or {}).get("machine") or {}
    return {
        "machine_id": machine,
        "registered": True,
        "name": record.get("name"),
        "owner_actor_id": record.get("owner_actor_id"),
        "access": record.get("access"),
        "retired_at": record.get("retired_at"),
    }


def _persist_credential(
    result: Mapping[str, Any], config_path: str | Path | None
) -> str | None:
    """Store an HTTPS machine bearer, returning recovery text on failure."""
    from yoke_cli.config import machine_config, writer
    from yoke_contracts.machine_config import schema as contract

    connection = machine_config.active_connection(config_path)
    if str(connection.get("transport") or "") != contract.TRANSPORT_HTTPS:
        return None
    credential = result.get("credential")
    token = credential.get("token") if isinstance(credential, Mapping) else None
    if not isinstance(token, str) or not token:
        return "machine_credential_unsupported: registration returned no bearer token"
    try:
        writer.set_credential(
            machine_config.active_env(config_path), token=token, path=config_path
        )
    except Exception as exc:  # noqa: BLE001 - actionable reconnect failure
        return f"machine_credential_store_failed: {exc}"
    return None


def error_text(error: Any) -> str:
    if isinstance(error, Mapping):
        return f"{error.get('code')}: {error.get('message')}"
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    if code or message:
        return f"{code}: {message}"
    return "machine registration was refused"


__all__ = [
    "REGISTER_ATTEMPTS",
    "REGISTER_RECOVERY_COMMAND",
    "REGISTER_TIMEOUT_S",
    "error_text",
    "register_this_machine",
    "show_this_machine",
]
