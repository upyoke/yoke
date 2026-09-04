"""Register this machine at connect time.

``yoke status`` makes the call rather than ``yoke onboard``: onboarding must
finish against a control plane that can only be inventoried, where a function
call answers 5xx and burns the whole connection retry ladder, while status
already knows whether the plane answered.

Registration is idempotent, and a refusal is returned as a reported reason
rather than raised: connecting a machine should not fail because the registry
disagreed, but the operator must be told which recovery to run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


REGISTER_TIMEOUT_S = 10.0


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
    }


def error_text(error: Any) -> str:
    if isinstance(error, Mapping):
        return f"{error.get('code')}: {error.get('message')}"
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    if code or message:
        return f"{code}: {message}"
    return "machine registration was refused"


__all__ = [
    "REGISTER_TIMEOUT_S",
    "error_text",
    "register_this_machine",
]
