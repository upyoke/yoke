"""Drive one operator-run test-machine operation the way the CLI drives it."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    TEST_MACHINE_SETTINGS,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_capability import (
    test_machine_detail as machine_detail,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_host_operation_contract,
)


ACTOR = ActorContext(actor_id="2", session_id="session-machine-two-phase")
MACHINE = TEST_MACHINE_SETTINGS["resource_name"]


def operation_request(payload: dict[str, Any]) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="test_machine.operation",
        actor=ACTOR,
        target=TargetRef(kind="global"),
        payload=payload,
    )


def begin_operation(
    operation: str,
    *,
    control: FakeHostControl,
    begin_payload: dict[str, Any] | None = None,
) -> Any:
    """Take the lease and issue the contract, with the host control bound."""
    register_host_control_factory(lambda _material: control)
    try:
        return handle_operation_begin(
            operation_request(
                {
                    "project": "yoke",
                    "operation": operation,
                    **(begin_payload or {}),
                }
            )
        )
    finally:
        clear_host_control_factory()


def run_operation(
    operation: str,
    *,
    control: FakeHostControl,
    begin_payload: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Begin, execute locally, and submit -- one whole operation."""
    register_host_control_factory(lambda _material: control)
    try:
        begun = handle_operation_begin(
            operation_request(
                {
                    "project": "yoke",
                    "operation": operation,
                    **(begin_payload or {}),
                }
            )
        )
        if not begun.primary_success:
            return begun, {}
        execution = begun.result_payload["execution"]
        submission = execute_host_operation_contract(execution)
        submitted = handle_operation_submit(
            operation_request(
                {
                    "project": "yoke",
                    "destination": execution.get("golden_destination"),
                    **(begin_payload or {}),
                    **submission.payload,
                }
            )
        )
    finally:
        clear_host_control_factory()
    return submitted, execution


def operation_receipts(conn: Any) -> list[dict[str, Any]]:
    return machine_detail(conn, project="yoke", machine=MACHINE)["operations"]


__all__ = [
    "ACTOR",
    "MACHINE",
    "begin_operation",
    "operation_receipts",
    "operation_request",
    "run_operation",
]
