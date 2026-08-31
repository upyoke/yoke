"""Persist a composed HTTPS Doctor report through ``doctor.run.run``."""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.api.function_call import TargetRef

from yoke_cli.commands._helpers import build_actor, call_dispatcher


def persist_composed_receipt(
    result: Dict[str, Any],
    *,
    session_id: str | None,
    timeout_s: float,
) -> None:
    """Write the merged HTTPS report; fail if the receipt call does not succeed."""
    response = call_dispatcher(
        function_id="doctor.run.run",
        target=TargetRef(kind="global"),
        payload={"receipt": result},
        actor=build_actor(session_id=session_id),
        timeout_s=timeout_s,
    )
    if not response.success:
        error = response.error
        code = error.code if error else "unknown"
        message = error.message if error else "the receipt call returned no diagnosis"
        raise RuntimeError(f"doctor run receipt persist failed ({code}): {message}")


__all__ = ["persist_composed_receipt"]
