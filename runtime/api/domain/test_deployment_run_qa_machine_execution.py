"""Deployment-run QA execution through the serial Test Mac."""

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    deployment_run,
    machine_plan,
)
from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.test_machine_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)
from yoke_core.domain.host_control_executor import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_machine_case_contract,
)
from yoke_core.domain.qa_plan_attachments import materialize_for_deployment_run
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.schema_init_tables import create_governed_tables


def test_deployment_plan_machine_case_uses_durable_serial_lease_and_evidence(
    test_db,
    tmp_path,
    monkeypatch,
) -> None:
    deployment_run(test_db)
    machine_plan(test_db)
    materialized = materialize_for_deployment_run(
        test_db,
        deployment_run_id=RUN_ID,
        plan="deployment-machine-smoke",
        project="yoke",
    )
    create_governed_tables(test_db)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN_ID,
        actor_id="2",
        session_id="deployment-machine",
    )
    requirement_id = materialized["created_requirement_ids"][0]

    def request(function: str, payload: dict | None = None):
        return FunctionCallRequest(
            function=function,
            actor=ActorContext(
                actor_id="2",
                session_id="deployment-machine",
            ),
            target=TargetRef(
                kind="deployment_run",
                deployment_run_id=RUN_ID,
            ),
            payload={
                "execution_id": str(execution["id"]),
                "ordinal": 0,
                "requirement_id": requirement_id,
                **(payload or {}),
            },
        )

    ready = handle_plan_case_begin(request("test_machine.plan_case.begin"))
    assert ready.primary_success, ready.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        submission = execute_machine_case_contract(ready.result_payload["execution"])
    finally:
        clear_host_control_factory()
    try:
        submitted = handle_plan_case_submit(
            request(
                "test_machine.plan_case.submit",
                submission.payload,
            )
        )
    finally:
        submission.cleanup_artifacts()
    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["cursor_ordinal"] == 1
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs "
            "WHERE qa_requirement_id=%s AND verdict='pass'",
            (requirement_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM coordination_leases WHERE released_at IS NULL"
        ).fetchone()[0]
        == 1
    )
    stored = lock_plan_execution(test_db, str(execution["id"]))
    finish_plan_execution(
        test_db,
        stored,
        state="completed",
        reason="deployment-machine-complete",
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM coordination_leases WHERE released_at IS NULL"
        ).fetchone()[0]
        == 0
    )
