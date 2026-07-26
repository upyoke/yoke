"""Execute one materialized Machine QA case through the registered surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS


class MachineCaseDispatchError(RuntimeError):
    """A materialized case cannot execute through ``host_control``."""


def execute_materialized_machine_case(
    case: Mapping[str, Any],
) -> dict[str, Any]:
    """Run one immutable case snapshot without trusting client-supplied proof.

    The server rereads the targeted requirement before controlling the host.
    The supplied snapshot is used only to refuse an incompatible generic-runner
    dispatch before it crosses the function boundary.
    """
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

    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id="test_machine.case_execute",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload={},
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise MachineCaseDispatchError(
            f"test_machine.case_execute failed ({code}): {message}"
        )
    result = dict(response.result or {})
    if int(result.get("requirement_id") or 0) != requirement_id:
        raise MachineCaseDispatchError(
            "test_machine.case_execute returned the wrong requirement"
        )
    return result


__all__ = [
    "MachineCaseDispatchError",
    "execute_materialized_machine_case",
]
