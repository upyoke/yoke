"""Successor QA keeps carried evidence; a fail on the old target is retried, not handed off.

A fail recorded against the predecessor's target reads as unrun once the case
rebinds, so no handoff goes out. A fail on the successor's own target still
gets the rework handoff when the merge is not provably contained.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_successor_retry_test_support import (
    HOLDER_A as HOLDER_A,
    MEMBER as MEMBER,
    _pinned_release as _pinned_release,
    _plan as _plan,
    _record as _record,
    _release as _release,
    _seed_member_execution as _seed_member_execution,
    _take_over_and_deploy as _take_over_and_deploy,
)


from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _bodies,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain.deployment_qa_failure_handoff import (
    failure_handoff_key,
    notify_member_qa_failure,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import (
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import (
    plan_execution_view,
    select_plan_execution,
)


def _status(conn):
    from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage

    materialize_deployment_qa_stage(conn, deployment_run_id=takeover.NEW,
        deployment_stage="item-qa", deployment_member_item_id=MEMBER)
    return deployment_qa_stage_status(
        conn, run_id=takeover.NEW, stage_name="item-qa", member_item_id=MEMBER
    )


def _handoff_bodies(conn, status, fail_run) -> list[str]:
    notify_member_qa_failure(
        conn, run_id=takeover.NEW, stage="item-qa", item_id=MEMBER, status=status
    )
    key = failure_handoff_key(
        takeover.NEW, "item-qa", MEMBER, str(status["target_digest"]), fail_run
    )
    return _bodies(conn, key)


def _stale_fail_waits_then_current_fail_reworks(conn, failed, fail_run) -> None:
    status = _status(conn)
    assert status["outcome"] == "waiting"
    assert (failed, "unrun") in {
        (int(f["requirement_id"]), f["kind"]) for f in status["case_failures"]
    }
    assert _handoff_bodies(conn, status, fail_run) == []
    current_fail = record_case_verdict(conn, failed, "fail", evidence=True)
    conn.execute(  # The retry on the successor's target is the newest attempt.
        "UPDATE qa_runs SET started_at=%s,completed_at=%s WHERE id=%s",
        ("2026-12-01T00:00:00Z", "2026-12-01T00:00:00Z", current_fail),
    )
    status = _status(conn)
    assert status["outcome"] == "blocked"
    [body] = _handoff_bodies(conn, status, current_fail)
    assert "Classify the failure and fix a finding in this item" in body
    assert "retry the case" not in body


def test_an_uncontained_merge_keeps_the_rework_handoff(test_db, monkeypatch):
    execution = _seed_member_execution(
        test_db,
        monkeypatch,
        producer="separate-qa-session",
    )
    _record(test_db, execution, 0, "pass")
    failed, fail_run = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    _take_over_and_deploy(test_db, monkeypatch, containment.UNDETERMINED)
    _stale_fail_waits_then_current_fail_reworks(test_db, failed, fail_run)


def test_a_failure_created_after_the_run_keeps_the_rework_handoff(test_db, monkeypatch):
    execution = _seed_member_execution(
        test_db, monkeypatch, producer="separate-qa-session"
    )
    _record(test_db, execution, 0, "pass")
    failed, fail_run = _record(
        test_db, execution, 1, "fail", created="2026-10-14T00:02:00Z"
    )
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    _take_over_and_deploy(test_db)
    _stale_fail_waits_then_current_fail_reworks(test_db, failed, fail_run)


def test_an_active_execution_continues_through_the_successor_deployment(
    test_db, monkeypatch
):
    execution = _seed_member_execution(test_db, monkeypatch)
    passed, pass_run = _record(test_db, execution, 0, "pass")
    test_db.execute(
        "UPDATE qa_plan_executions SET test_machine_lease_id=4242 WHERE id=%s",
        (execution["id"],),
    )
    test_db.commit()
    _take_over_and_deploy(test_db)

    moved = select_plan_execution(test_db, execution["id"], lock=False)
    assert moved["id"] == execution["id"]
    assert moved["state"] == "active"
    assert moved["deployment_run_id"] == takeover.NEW
    assert moved["test_machine_lease_id"] == 4242
    assert moved["roster_digest"] == execution["roster_digest"]
    view = plan_execution_view(test_db, moved)
    assert [row["requirement_id"] for row in view["results"]] == [passed]
    assert _release(view) == "v-cccccc"
    # The walk resumes at its cursor: the next case records, nothing replays.
    _record(test_db, moved, 1, "pass")
    finished = select_plan_execution(test_db, execution["id"], lock=False)
    assert [
        row["requirement_id"]
        for row in plan_execution_view(test_db, finished)["results"]
    ] == [passed, int(moved["roster"][1]["requirement_id"])]
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (pass_run,)
        ).fetchone()[0]
        == "pass"
    )
