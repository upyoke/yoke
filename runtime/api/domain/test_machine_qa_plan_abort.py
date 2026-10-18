"""Cooperative cancellation stops host actions and requires restoration proof."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.test_machine_qa_chain_restore import _contract
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain.machine_qa_phase_heartbeat import (
    MachineQaAborted,
    check_abort,
    heartbeat_during,
)


def test_abort_stops_before_the_next_host_step_and_records_restore(monkeypatch):
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    reached, steps = [], []
    cancelled = False

    def reach(name):
        reached.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={"checked": name})

    def progress():
        return {"abort_requested": cancelled}

    def run_case(execution, case):
        nonlocal cancelled
        steps.append("first")
        cancelled = True
        execution.progress_callback()
        steps.append("must not run")

    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(
        local,
        "_execution",
        lambda c, **kw: SimpleNamespace(
            material=SimpleNamespace(secrets={}), reach_baseline=reach, **kw
        ),
    )
    monkeypatch.setattr(local, "execute_case_with_fixture_lifecycle", run_case)
    row = local.execute_machine_case_contract({}, progress_callback=progress).payload[
        "results"
    ][0]
    assert steps == ["first"]
    assert reached == ["fresh-host", "fresh-host"]
    assert row["error_code"] == "qa_host_abort_requested"
    assert row["evidence"]["abort"]["host_work_stopped"]
    assert row["evidence"]["starting_state_restore"]["restored"]


def test_abort_signal_crosses_heartbeat_boundary_after_safe_phase():
    finished = []
    with pytest.raises(MachineQaAborted):
        with heartbeat_during(
            "starting_state_reset", lambda: {"abort_requested": True}
        ):
            finished.append(True)
    assert finished == [True]


def test_cleanup_finishes_despite_abort_signal():
    with heartbeat_during(
        "fixture_cleanup", lambda: {"abort_requested": True}, propagate_abort=False
    ):
        pass
    with pytest.raises(MachineQaAborted):
        check_abort(lambda: {"abort_requested": True})


@pytest.mark.parametrize("restored", [True, False])
def test_server_retains_lease_until_submitted_restore_proof(
    test_db, tmp_path, monkeypatch, restored
):
    from runtime.api.domain.test_machine_qa_plan_execution import (
        ACTOR,
        _request,
        _active_lease_count,
    )
    from runtime.api.domain.machine_qa_host_test_support import (
        configure_test_machine,
        materialize_installer_campaign,
    )
    from yoke_core.domain.handlers.machine_qa_plan_case import (
        handle_plan_case_begin,
        handle_plan_case_submit,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        begin_plan_execution,
        lock_plan_execution,
        heartbeat_plan_execution,
        finish_plan_execution,
    )
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
    from yoke_core.domain.qa_plan_execution_reentry import checkin_view

    item_id = 4550
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    heartbeat_plan_execution(test_db, execution)
    case = execution["roster"][0]
    ready = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution["id"],
            ordinal=0,
            requirement_id=case["requirement_id"],
        )
    )
    assert ready.primary_success, ready.error
    execution = lock_plan_execution(test_db, execution["id"])
    original_title = test_db.execute(
        "SELECT title FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    test_db.execute(
        "UPDATE items SET title=%s WHERE id=%s", ("uncommitted caller change", item_id)
    )
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_required"):
        finish_plan_execution(
            test_db,
            execution,
            state="aborted",
            reason="nested cancellation",
            commit=False,
        )
    test_db.rollback()
    assert (
        test_db.execute("SELECT title FROM items WHERE id=%s", (item_id,)).fetchone()[0]
        == original_title
    )
    execution = lock_plan_execution(test_db, execution["id"])
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_pending"):
        finish_plan_execution(
            test_db, execution, state="aborted", reason="operator cancelled"
        )
    assert _active_lease_count(test_db) == 1
    current = lock_plan_execution(test_db, execution["id"])
    heartbeat_plan_execution(test_db, current)
    assert checkin_view(current)["abort_requested"]
    issued = ready.result_payload["execution"]
    evidence = {
        "runner_id": "host_control",
        "machine": "mac-mini-lab",
        "method_id": case["method_id"],
        "baseline": issued["baselines"][0],
        "abort": {"host_work_stopped": True},
        "starting_state_restore": {
            "baseline": case["host_baseline"],
            "restored": restored,
        },
    }
    submitted = handle_plan_case_submit(
        _request(
            "test_machine.plan_case.submit",
            item_id=item_id,
            execution_id=execution["id"],
            ordinal=0,
            requirement_id=case["requirement_id"],
            payload={
                "lease_id": issued["lease_id"],
                "contract_digest": issued["contract_digest"],
                "results": [
                    {
                        "requirement_id": case["requirement_id"],
                        "case_outcome": "failed",
                        "verdict": "fail",
                        "error_code": "qa_host_abort_requested",
                        "duration_ms": 1,
                        "evidence": evidence,
                    }
                ],
            },
        )
    )
    assert submitted.primary_success, submitted.error
    current = lock_plan_execution(test_db, execution["id"])
    assert current["state"] == ("aborted" if restored else "active")
    assert _active_lease_count(test_db) == (0 if restored else 1)
    if restored:
        finish_plan_execution(
            test_db, current, state="aborted", reason="operator cancelled"
        )
    else:
        with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_pending"):
            finish_plan_execution(
                test_db, current, state="aborted", reason="operator cancelled"
            )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s AND raw_result LIKE %s",
            (case["requirement_id"], "%starting_state_restore%"),
        ).fetchone()[0]
        == 1
    )
