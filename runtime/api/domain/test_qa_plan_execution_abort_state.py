"""Abort cleanup follows the interrupted case's declared starting state."""

import json
from unittest.mock import Mock

import pytest

from yoke_core.domain import qa_plan_execution_abort_state as abort
from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON


@pytest.mark.parametrize(
    ("starting_state", "baseline", "receipt", "expected"),
    [
        ("baseline", "fresh-host", {"restored": True, "baseline": "fresh-host"}, True),
        (
            "baseline",
            "fresh-host",
            {"restored": False, "baseline": "fresh-host"},
            False,
        ),
        ("baseline", "fresh-host", {"restored": True, "baseline": "other"}, False),
        ("as_is", None, {"restored": False, "reason": "no declared baseline"}, True),
        ("inherit", None, {"restored": False, "reason": "no declared baseline"}, True),
        ("as_is", "unused", {"restored": False, "reason": "as found"}, True),
        ("as_is", None, {}, False),
        ("baseline", "fresh-host", {}, False),
    ],
)
def test_cleanup_receipt_matches_interrupted_case(
    monkeypatch, starting_state, baseline, receipt, expected
):
    execution = {
        "id": "execution",
        "roster": [
            {"runner_id": "host_control", "host_baseline": "other"},
            {
                "runner_id": "host_control",
                "starting_state": starting_state,
                "host_baseline": baseline,
            },
        ],
    }
    monkeypatch.setattr(
        abort,
        "result_rows",
        lambda *_: [{"ordinal": 1, "requirement_id": 10, "result": {"run_id": 20}}],
    )
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = (
        json.dumps({"evidence": {"starting_state_restore": receipt}}),
    )
    assert abort.host_cleanup_proven(conn, execution, 1) is expected


def test_another_cases_receipt_cannot_release_interrupted_case(monkeypatch):
    monkeypatch.setattr(
        abort,
        "result_rows",
        lambda *_: [{"ordinal": 0, "requirement_id": 10, "result": {"run_id": 20}}],
    )
    conn = Mock()
    execution = {"id": "execution", "roster": [{}, {"starting_state": "as_is"}]}
    assert not abort.host_cleanup_proven(conn, execution, 1)
    conn.execute.assert_not_called()


def test_non_host_interruption_does_not_owe_another_cases_restore():
    conn = Mock()
    execution = {
        "test_machine_lease_id": 1,
        "cursor_ordinal": 1,
        "release_reason": PAUSE_REASON + json.dumps({"case_inflight": 1}),
        "roster": [
            {"runner_id": "host_control", "host_baseline": "fresh-host"},
            {"runner_id": "worktree_run"},
        ],
    }
    abort.require_host_restored(conn, execution, reason="stop", commit=False)
    conn.execute.assert_not_called()


def test_remove_member_with_as_is_cleanup_releases_host(test_db, tmp_path, monkeypatch):
    from runtime.api.domain.test_qa_member_machine_partitions import (
        MEMBER,
        RUN,
        _seed,
        _begin,
        _case_begin,
    )
    from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        heartbeat_plan_execution,
        lock_plan_execution,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (MEMBER,))
    test_db.commit()
    release_seeded_driver(test_db, RUN)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    execution = lock_plan_execution(test_db, execution["id"])
    heartbeat_plan_execution(test_db, execution)
    leases = execution_host_leases(test_db, execution)
    assert leases
    case = execution["roster"][0]
    now = utc_now()
    run_id = insert_qa_run(
        test_db,
        qa_requirement_id=case["requirement_id"],
        performed_by="host_control",
        qa_kind="plan_case",
        verdict="fail",
        raw_result=json.dumps(
            {
                "evidence": {
                    "starting_state_restore": {
                        "restored": False,
                        "reason": "no declared starting state to restore",
                    }
                }
            }
        ),
        started_at=now,
        completed_at=now,
        created_at=now,
    ).run_id
    advance_plan_execution(
        test_db,
        execution,
        ordinal=0,
        requirement_id=case["requirement_id"],
        result={
            "run_id": run_id,
            "case_outcome": "failed",
            "verdict": "fail",
        },
    )
    cmd_remove_item(
        RUN, MEMBER, reason="cancel cleaned case", session_id="remover", actor_id=1
    )
    assert lock_plan_execution(test_db, execution["id"])["state"] == "aborted"
    assert not execution_host_leases(test_db, execution)
    assert not test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBER),
    ).fetchone()
    assert all(
        test_db.execute(
            "SELECT released_at FROM work_claims WHERE id=%s",
            (lease.id,),
        ).fetchone()[0]
        for lease in leases
    )
