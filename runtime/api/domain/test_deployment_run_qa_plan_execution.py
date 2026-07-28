"""Deployment-run materialization and durable QA execution coverage."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    atomic_command_plan,
    command_plan,
    deployment_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_deployment_run,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    plan_execution_view,
    require_plan_execution_owner,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_registry import (
    lookup,
    reset_registry_for_tests,
)


def test_named_plan_materializes_and_executes_against_deployment_run() -> None:
    with test_database() as conn:
        deployment_run(conn)
        plan_id = command_plan(conn)
        first = materialize_for_deployment_run(
            conn,
            deployment_run_id=RUN_ID,
            plan="deployment-smoke",
            project="yoke",
        )
        second = materialize_for_deployment_run(
            conn,
            deployment_run_id=RUN_ID,
            plan=str(plan_id),
            project="yoke",
        )
        requirement_id = first["created_requirement_ids"][0]
        requirement = conn.execute(
            "SELECT item_id,deployment_run_id,qa_phase,"
            "workflow_transition_id FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
        context = get_case_execution_context(
            conn,
            requirement_id=requirement_id,
        )
        execution = begin_plan_execution(
            conn,
            deployment_run_id=RUN_ID,
            actor_id="7",
            session_id="deployment-qa",
        )
        view = plan_execution_view(conn, execution)
        with pytest.raises(
            QaPlanExecutionStateError,
            match="different deployment run",
        ):
            require_plan_execution_owner(
                execution,
                deployment_run_id="run-20260728-902",
                actor_id="7",
                session_id="deployment-qa",
            )
        with pytest.raises(
            QaPlanExecutionStateError,
            match="different actor or session",
        ):
            require_plan_execution_owner(
                execution,
                deployment_run_id=RUN_ID,
                actor_id="7",
                session_id="other-session",
            )

    assert tuple(requirement) == (None, RUN_ID, "post_deploy", None)
    assert second["created_requirement_ids"] == []
    assert second["existing_requirement_ids"] == [requirement_id]
    assert context["item_id"] is None
    assert context["deployment_run_id"] == RUN_ID
    assert context["project"] == "yoke"
    assert view["item_id"] is None
    assert view["deployment_run_id"] == RUN_ID
    assert view["transition_id"] is None
    assert [case["requirement_id"] for case in view["requirements"]] == [requirement_id]


def test_deployment_plan_snapshot_rolls_back_as_one_transaction() -> None:
    with test_database() as conn:
        deployment_run(conn)
        atomic_command_plan(conn)
        from yoke_core.domain import qa_plan_attachments

        real_insert = qa_plan_attachments.insert_requirement
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated materialization interruption")
            return real_insert(*args, **kwargs)

        with (
            mock.patch.object(
                qa_plan_attachments,
                "insert_requirement",
                side_effect=fail_second,
            ),
            pytest.raises(
                RuntimeError,
                match="simulated materialization interruption",
            ),
        ):
            materialize_for_deployment_run(
                conn,
                deployment_run_id=RUN_ID,
                plan="atomic-deployment-smoke",
                project="yoke",
            )
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s",
            (RUN_ID,),
        ).fetchone()[0]

    assert count == 0


def test_deployment_requirement_evidence_writes_use_the_run_subject() -> None:
    with test_database() as conn:
        deployment_run(conn)
        command_plan(conn)
        materialized = materialize_for_deployment_run(
            conn,
            deployment_run_id=RUN_ID,
            plan="deployment-smoke",
            project="yoke",
        )
        requirement_id = materialized["created_requirement_ids"][0]
        request = FunctionCallRequest(
            function="qa.run.add",
            actor=ActorContext(
                actor_id="2",
                session_id="deployment-evidence",
            ),
            target=TargetRef(
                kind="qa_requirement",
                qa_requirement_id=requirement_id,
            ),
            payload={},
        )
        reset_registry_for_tests()
        try:
            register_all_handlers()
            for function_id in (
                "qa.requirement.update",
                "qa.requirement.waive",
                "qa.run.add",
                "qa.run.complete",
                "qa.run.record_verdict",
                "qa.artifact.add",
                "qa.artifact.presign",
            ):
                entry = lookup(function_id)
                assert entry is not None
                assert entry.claim_required_kind == "qa_subject"
                request.function = function_id
                assert verify_claim(entry, request) is None
        finally:
            reset_registry_for_tests()
