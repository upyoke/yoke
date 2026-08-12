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
    runner_id = str(case.get("runner_id") or "")
    method_id = str(case.get("method_id") or "")
    if requirement_id < 1:
        raise MachineCaseDispatchError("Machine QA requires requirement_id")
    if runner_id != "host_control" or method_id not in MACHINE_METHODS:
        raise MachineCaseDispatchError(
            f"case {requirement_id} is not a registered Machine QA case"
        )
    for key in ("project", "method_config", "entry_surface", "required_completion"):
        if key not in case:
            raise MachineCaseDispatchError(
                f"Machine QA execution context is missing {key}"
            )
    return requirement_id


def _dispatch_machine_function(
    function_id: str,
    requirement_id: int,
    *,
    actor: ActorContext | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=function_id,
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload=dict(payload or {}),
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise MachineCaseDispatchError(
            f"{function_id} failed ({code}): {message}"
        )
    return dict(response.result or {})


def _actor(actor: ActorContext | None) -> ActorContext:
    if actor is not None:
        return actor
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    return build_actor()


def _abort_issued_contract(
    *,
    abort_function: str,
    requirement_id: int,
    actor: ActorContext,
    execution: dict[str, Any],
    reason: str,
) -> bool:
    lease_id = execution.get("lease_id")
    contract_digest = execution.get("contract_digest")
    if not isinstance(lease_id, int) or not isinstance(contract_digest, str):
        return False
    try:
        _dispatch_machine_function(
            abort_function,
            requirement_id,
            actor=actor,
            payload={
                "lease_id": lease_id,
                "contract_digest": contract_digest,
                "reason": reason,
            },
        )
    except MachineCaseDispatchError:
        return False
    return True


def _execute_issued_contract(
    *,
    begin_function: str,
    submit_function: str,
    abort_function: str,
    requirement_id: int,
    actor: ActorContext | None,
) -> dict[str, Any]:
    resolved_actor = _actor(actor)
    begun = _dispatch_machine_function(
        begin_function,
        requirement_id,
        actor=resolved_actor,
    )
    if begun.get("state") == "waiting":
        result = begun.get("result")
        if not isinstance(result, dict):
            raise MachineCaseDispatchError(
                f"{begin_function} returned an invalid waiting result"
            )
        return result
    execution = begun.get("execution")
    if begun.get("state") != "ready" or not isinstance(execution, dict):
        raise MachineCaseDispatchError(
            f"{begin_function} returned no execution contract"
        )
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            execute_machine_case_contract,
        )
        from yoke_core.domain.ssh_mac_host_control import (
            register_ssh_mac_host_control,
        )

        register_ssh_mac_host_control()
        submission = execute_machine_case_contract(execution)
    except BaseException as exc:
        released = _abort_issued_contract(
            abort_function=abort_function,
            requirement_id=requirement_id,
            actor=resolved_actor,
            execution=execution,
            reason="local_execution_failed",
        )
        if not isinstance(exc, Exception):
            raise
        raise MachineCaseDispatchError(
            "local host-control execution failed "
            f"({type(exc).__name__}); "
            + (
                "the server lease was released"
                if released
                else "automatic server-lease release also failed"
            )
        ) from exc
    try:
        submitted = _dispatch_machine_function(
            submit_function,
            requirement_id,
            actor=resolved_actor,
            payload=submission.payload,
        )
    except MachineCaseDispatchError:
        _abort_issued_contract(
            abort_function=abort_function,
            requirement_id=requirement_id,
            actor=resolved_actor,
            execution=execution,
            reason="submission_failed",
        )
        submission.cleanup_artifacts()
        raise
    submission.cleanup_artifacts()
    return submitted


def execute_materialized_machine_case(
    case: Mapping[str, Any],
    *,
    actor: ActorContext | None = None,
) -> dict[str, Any]:
    """Rerun one immutable case through the begin/local/submit protocol.

    The server rereads the target and issues the only contract the local
    credential-owning process may execute. The supplied snapshot is used only
    to refuse an incompatible generic-runner dispatch before that boundary.
    """
    requirement_id = _require_machine_case(case)
    result = _execute_issued_contract(
        begin_function="test_machine.case.begin",
        submit_function="test_machine.case.submit",
        abort_function="test_machine.case.abort",
        requirement_id=requirement_id,
        actor=actor,
    )
    if int(result.get("requirement_id") or 0) != requirement_id:
        raise MachineCaseDispatchError(
            "test_machine.case.submit returned the wrong requirement"
        )
    return result


def execute_materialized_machine_baseline_group(
    case: Mapping[str, Any],
    *,
    actor: ActorContext | None = None,
) -> dict[str, Any]:
    """Run the server-discovered baseline group locally under one lease."""
    requirement_id = _require_machine_case(case)
    if case.get("plan_id") is None or not case.get("host_baseline"):
        raise MachineCaseDispatchError(
            "Machine QA baseline-group execution requires a plan-backed "
            "case with host_baseline"
        )
    result = _execute_issued_contract(
        begin_function="test_machine.baseline_group.begin",
        submit_function="test_machine.baseline_group.submit",
        abort_function="test_machine.baseline_group.abort",
        requirement_id=requirement_id,
        actor=actor,
    )
    if int(result.get("anchor_requirement_id") or 0) != requirement_id:
        raise MachineCaseDispatchError(
            "test_machine.baseline_group.submit returned the wrong anchor"
        )
    requirement_ids = {
        int(value) for value in result.get("requirement_ids") or []
    }
    if requirement_id not in requirement_ids:
        raise MachineCaseDispatchError(
            "test_machine.baseline_group.submit omitted its anchor"
        )
    return result


__all__ = [
    "MachineCaseDispatchError",
    "execute_materialized_machine_baseline_group",
    "execute_materialized_machine_case",
]
