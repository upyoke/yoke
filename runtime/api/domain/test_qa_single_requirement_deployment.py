"""A deployment case selector preserves its run and unrelated requirements."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.deployment_run_qa_plan_execution_test_support import (
    RUN_ID,
    atomic_command_plan,
    deployment_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_attachments import materialize_for_deployment_run
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_member_plan_execution import execute_serial_partitions


def test_deployment_roster_selects_one_requirement_without_a_plan_filter():
    with test_database() as conn:
        deployment_run(conn)
        plan_id = atomic_command_plan(conn)
        result = materialize_for_deployment_run(
            conn,
            deployment_run_id=RUN_ID,
            plan=str(plan_id),
            project="yoke",
        )
        first, selected = result["created_requirement_ids"]
        execution = begin_plan_execution(
            conn,
            deployment_run_id=RUN_ID,
            requirement_id=selected,
            actor_id="7",
            session_id="single-deployment-case",
        )
        assert [r["requirement_id"] for r in execution["roster"]] == [selected]
        assert (
            conn.execute(
                "SELECT waived_at FROM qa_requirements WHERE id=%s", (first,)
            ).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM qa_runs WHERE qa_requirement_id=%s", (first,)
            ).fetchone()[0]
            == 0
        )


def test_single_requirement_never_continues_into_sibling_partitions():
    runner = Mock(return_value={"state": "passed", "remaining_requirement_count": 5})
    result = execute_serial_partitions(runner)(
        requirement_id=51,
        deployment_stage="item-qa",
        deployment_member="member",
    )
    runner.assert_called_once()
    assert result["remaining_requirement_count"] == 5


def test_selected_shared_subject_retries_a_changed_run_before_starting():
    from yoke_core.domain import deployment_qa_shared_plans as shared
    from yoke_core.domain import qa_plan_execution_begin_admission as admission
    from yoke_core.domain.deployment_qa_shared_execution import (
        route_shared_plan_execution,
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            shared,
            "requirement_subject",
            Mock(return_value={"shared_plan": {"plan_id": 3}}),
        )
        patch.setattr(admission, "begin_inputs", Mock(side_effect=["before", "after"]))
        begin = Mock(
            side_effect=[admission.BeginInputsChanged("release-run"), {"id": "one"}]
        )
        conn = Mock()
        result = route_shared_plan_execution(begin)(
            conn,
            requirement_id=51,
            deployment_run_id="release-run",
            deployment_stage="qa",
        )
    assert result == {"id": "one"}
    conn.rollback.assert_called_once()
    assert begin.call_args.kwargs["_run_inputs"] == "after"
    assert begin.call_args.kwargs["_deployment_subject"] == {
        "shared_plan": {"plan_id": 3}
    }


@pytest.mark.parametrize(
    "state,code", [("awaiting_agent_review", 12), ("failed", 1), ("waiting", 3)]
)
def test_case_cli_uses_plan_review_and_exit_semantics(monkeypatch, state, code):
    from yoke_core.domain import qa_case_execution_cli as cli
    from yoke_core.domain import qa_plan_execution_cli as plan_cli

    result = {"execution_id": "single-mission", "state": state, "results": []}
    monkeypatch.setattr(cli, "execute_case", Mock(return_value=result))
    qualify = Mock()
    monkeypatch.setattr(plan_cli, "_qualify_review_dispatch", qualify)
    assert cli.run(["--requirement-id", "51"]) == code
    assert qualify.call_count == (1 if state == "awaiting_agent_review" else 0)


def test_review_wake_resumes_the_frozen_execution_instead_of_the_whole_scope(test_db):
    from runtime.api.domain.test_qa_plan_agent_review_wake import _owner
    from runtime.api.domain.test_qa_capture_pending_review import _seed_pending
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _bodies

    _owner(test_db)
    execution, _bundle, _requirement = _seed_pending(
        test_db, "run-single-review-wake", "item"
    )
    [body] = _bodies(test_db, f"qa-plan-agent-review:{execution['id']}")
    assert f"--resume-execution-id {execution['id']}" in body


def test_host_wait_resumes_the_frozen_execution(monkeypatch):
    from yoke_core.domain import qa_host_turns as turns
    from yoke_core.domain import qa_plan_execution_continuation as continuation

    monkeypatch.setattr(
        turns,
        "query_one",
        lambda *a, **k: {
            "id": "selected-execution",
            "roster_json": "[]",
        },
    )
    command = (
        "yoke qa plan run --deployment-run-id release --stage qa --project example"
    )
    monkeypatch.setattr(
        continuation, "continuation_recipe", lambda *a: command + " --continue-mission"
    )
    actual = turns._resume_command(
        Mock(), {"qa_plan_execution_id": "selected-execution"}
    )
    assert actual == command + " --resume-execution-id selected-execution"
