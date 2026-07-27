"""Execute one materialized Machine QA case through the registered surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS


class MachineCaseDispatchError(RuntimeError):
    """A materialized case cannot execute through ``host_control``."""


def _require_machine_case(case: Mapping[str, Any]) -> int:
    requirement_id = int(case.get("requirement_id") or 0)
    executor_id = str(case.get("executor_id") or "")
    method_id = str(case.get("method_id") or "")
    if requirement_id < 1:
        raise MachineCaseDispatchError("Machine QA requires requirement_id")
    if executor_id != "host_control" or method_id not in MACHINE_METHODS:
        raise MachineCaseDispatchError(
            f"case {requirement_id} is not a registered Machine QA case"
        )
    for key in ("project", "method_config", "entry_surface", "required_completion"):
        if key not in case:
            raise MachineCaseDispatchError(
                f"Machine QA execution context is missing {key}"
            )
    return requirement_id


def _dispatch_machine_case(
    function_id: str,
    requirement_id: int,
    *,
    actor: ActorContext | None,
) -> dict[str, Any]:
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=function_id,
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload={},
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise MachineCaseDispatchError(
            f"{function_id} failed ({code}): {message}"
        )
    return dict(response.result or {})


def execute_materialized_machine_case(
    case: Mapping[str, Any],
    *,
    actor: ActorContext | None = None,
) -> dict[str, Any]:
    """Rerun one immutable case without trusting client-supplied proof.

    The server rereads the targeted requirement before controlling the host.
    The supplied snapshot is used only to refuse an incompatible generic-runner
    dispatch before it crosses the function boundary.
    """
    requirement_id = _require_machine_case(case)
    result = _dispatch_machine_case(
        "test_machine.case_execute",
        requirement_id,
        actor=actor,
    )
    if int(result.get("requirement_id") or 0) != requirement_id:
        raise MachineCaseDispatchError(
            "test_machine.case_execute returned the wrong requirement"
        )
    return result


def execute_materialized_machine_baseline_group(
    case: Mapping[str, Any],
    *,
    actor: ActorContext | None = None,
) -> dict[str, Any]:
    """Run the anchor's server-discovered baseline group under one lease."""
    requirement_id = _require_machine_case(case)
    if case.get("plan_id") is None or not case.get("host_baseline"):
        raise MachineCaseDispatchError(
            "Machine QA baseline-group execution requires a plan-backed "
            "case with host_baseline"
        )
    result = _dispatch_machine_case(
        "test_machine.baseline_group_execute",
        requirement_id,
        actor=actor,
    )
    if int(result.get("anchor_requirement_id") or 0) != requirement_id:
        raise MachineCaseDispatchError(
            "test_machine.baseline_group_execute returned the wrong anchor"
        )
    requirement_ids = {
        int(value) for value in result.get("requirement_ids") or []
    }
    if requirement_id not in requirement_ids:
        raise MachineCaseDispatchError(
            "test_machine.baseline_group_execute omitted its anchor"
        )
    return result


__all__ = [
    "MachineCaseDispatchError",
    "execute_materialized_machine_baseline_group",
    "execute_materialized_machine_case",
]
