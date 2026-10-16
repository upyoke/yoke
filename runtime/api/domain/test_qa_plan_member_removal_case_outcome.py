"""A case cut off by its member's removal reports removed, not a host failure."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_plan_execution_test_support import TEST_EXECUTION_TARGET
from runtime.api.domain.test_deployment_member_execution_removal import (
    _execution,
    _request,
)
from runtime.api.domain.test_deployment_qa_stage_member_removal import (
    REMOVED,
    RUN,
    _ready_run,
)
from runtime.api.domain.test_qa_host_turns import _notices
from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.machine_qa_failures import host_control_failure
from yoke_core.domain import machine_qa_plan_case_execution, qa_plan_execution
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_abort
from yoke_core.domain.qa_plan_execution_abort_reason import member_removed

CASE = {
    "requirement_id": 47794,
    "deployment_run_id": RUN,
    "plan_id": 4,
    "case_key": "hosted-connect",
    "case_position": 1,
    "baseline_position": 1,
    "host_baseline": "fresh-host",
    "starting_state": "baseline",
    "runner_id": "host_control",
}


def _host_failure() -> machine_qa_plan_case_execution.MachinePlanCaseDispatchError:
    """The error the case's catch-all raises when its heartbeat is refused."""
    code, message, recovery = host_control_failure(
        RuntimeError("QA plan execution cannot heartbeat"),
        phase="plan_case_local_execution",
    )
    return machine_qa_plan_case_execution.MachinePlanCaseDispatchError(
        message, error_code=code, recovery_hint=recovery
    )


def _run_plan(test_db, execution_id: str, *, remove: bool, abort_view=None):
    """Drive the client loop; the abort reaches the real handler unless faked."""

    def call_plan_function(**kwargs):
        function_id = kwargs["function_id"]
        if function_id == "qa.plan_execution.begin":
            return {
                "execution_id": execution_id,
                "deployment_run_id": RUN,
                "deployment_stage": "item-qa",
                "deployment_member_item_id": REMOVED,
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 0,
                "execution_target": TEST_EXECUTION_TARGET,
                "execution_target_digest": "target-digest",
                "requirements": [CASE],
                "results": [],
            }
        if function_id == "qa.plan_execution.abort":
            if abort_view is not None:
                return abort_view
            outcome = handle_plan_execution_abort(_request(execution_id))
            assert outcome.primary_success
            return outcome.result_payload
        return {}

    def run_case(case, **_):
        if remove:
            remove_member_on(test_db, RUN, REMOVED, reason="QA waits for a later run")
            test_db.commit()
        raise _host_failure()

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=call_plan_function
        ),
        mock.patch.object(
            machine_qa_plan_case_execution,
            "execute_plan_machine_case",
            side_effect=run_case,
        ),
    ):
        return qa_plan_execution.execute_plan(
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member=str(REMOVED),
            actor=ActorContext(actor_id="1", session_id="removed-qa"),
        )


def test_member_removal_mid_case_reports_removed_not_a_host_failure(
    test_db, monkeypatch
):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa")
    _notices(monkeypatch)
    execution_id = _execution(test_db, state="active")

    result = _run_plan(test_db, execution_id, remove=True)

    assert result["state"] == "removed"
    assert result["results"] == [
        {
            "requirement_id": 47794,
            "plan_id": 4,
            "case_key": "hosted-connect",
            "case_position": 1,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "case_outcome": "removed",
        }
    ]
    assert "host_control_local_execution_failed" not in str(result)
    assert "cancelled with nothing recorded as passed" in result["recovery"]
    assert "no host needs repair" in result["recovery"]
    stored = test_db.execute(
        "SELECT state,release_reason FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    assert tuple(stored) == ("aborted", "deployment-member-removed")


def test_abort_of_a_removed_member_execution_returns_the_removal_reason(
    test_db, monkeypatch
):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa")
    _notices(monkeypatch)
    execution_id = _execution(test_db, state="active")
    remove_member_on(test_db, RUN, REMOVED, reason="QA waits for a later run")
    test_db.commit()

    outcome = handle_plan_execution_abort(_request(execution_id))

    assert outcome.primary_success
    assert outcome.result_payload["release_reason"] == "deployment-member-removed"
    assert member_removed(outcome.result_payload)


def test_a_host_failure_without_removal_still_reports_the_host_error(
    test_db, monkeypatch
):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa")
    _notices(monkeypatch)
    execution_id = _execution(test_db, state="active")

    result = _run_plan(test_db, execution_id, remove=False)

    assert result["state"] == "error"
    assert result["results"][0]["case_outcome"] == "error"
    assert "host_control_local_execution_failed" in result["results"][0]["error"]
    assert not member_removed({"state": "aborted"})


def test_a_server_without_release_reason_reports_the_host_error_as_before(
    test_db,
):
    result = _run_plan(
        test_db, "execution-old-server", remove=False, abort_view={"state": "aborted"}
    )

    assert result["state"] == "error"
    assert result["results"][0]["case_outcome"] == "error"
