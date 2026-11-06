"""Creating a run takes over an older run on its target that waits on QA."""

from __future__ import annotations

from runtime.api.domain.deployment_run_target_takeover_test_support import (_memberless_copy as _memberless_copy)

from runtime.api.domain.deployment_run_target_takeover_test_support import (
    NEW as NEW,
    NEW_LINEAGE as NEW_LINEAGE,
    OLD as OLD,
    OLD_LINEAGE as OLD_LINEAGE,
    PASSED as PASSED,
    RUN_QA_STAGE as RUN_QA_STAGE,
    WAITING as WAITING,
    _close_passed as _close_passed,
    _dated_copy,
    _dated_target,
    _contains as _contains,
    _members as _members,
    _requirement as _requirement,
    _run as _run,
    _seed_new as _seed_new,
    _seed_old as _seed_old,
    _take_over as _take_over,
)


import pytest

from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain.deployment_run_target_takeover import (
    NOT_CONTAINED_CODE,
    TakeoverRefused,
    take_over_waiting_run,
)
from yoke_core.domain.deploy_target_occupancy import open_qa_lines


def _open_memberless(conn, run_id: str) -> list:
    return conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id IS NULL AND retracted_at IS NULL "
        "AND waived_at IS NULL",
        (run_id,),
    ).fetchall()


def test_without_run_qa_open_members_move_and_the_older_run_succeeds(
    test_db, monkeypatch
):
    cases = _seed_old(test_db, run_qa=False)
    stranded = _memberless_copy(test_db, cases[WAITING])
    _close_passed(test_db)
    _seed_new(test_db)
    _contains(monkeypatch)
    assert open_qa_lines(test_db, OLD)

    assert _take_over(test_db) == OLD

    assert _members(test_db, OLD) == {PASSED}
    assert _members(test_db, NEW) == {WAITING}
    assert removed_item_ids(test_db, OLD) == {WAITING}
    old, new = _run(test_db, OLD), _run(test_db, NEW)
    assert old["status"] == "succeeded" and old["superseded_by_run_id"] == NEW
    assert new["supersedes_run_id"] == OLD
    retracted = test_db.execute(
        "SELECT id,deployment_run_id,retracted_at FROM qa_requirements WHERE id IN (%s,%s)",
        (cases[WAITING], stranded),
    ).fetchall()
    assert all(
        row["retracted_at"] is None and row["deployment_run_id"] == NEW
        for row in retracted
    )
    passed = test_db.execute(
        "SELECT retracted_at FROM qa_requirements WHERE id=%s", (cases[PASSED],)
    ).fetchone()
    assert passed["retracted_at"] is None
    assert _open_memberless(test_db, OLD) == []


def test_a_passed_member_not_yet_closed_moves_and_the_empty_run_is_cancelled(
    test_db, monkeypatch
):
    """Passed item QA alone is not enough to stay: only a closed member did
    the older run deliver, so a run left with none is cancelled, not green."""
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD

    assert _members(test_db, OLD) == set()
    assert _members(test_db, NEW) == {PASSED, WAITING}
    assert removed_item_ids(test_db, OLD) == {PASSED, WAITING}
    assert _run(test_db, OLD)["status"] == "cancelled"
    assert _open_memberless(test_db, OLD) == []


def test_with_run_qa_every_unclosed_member_moves_and_nothing_passes(
    test_db, monkeypatch
):
    cases = _seed_old(test_db, run_qa=True)
    run_check = _memberless_copy(test_db, cases[WAITING], stage=RUN_QA_STAGE)
    _seed_new(test_db)
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD

    assert _members(test_db, OLD) == set()
    assert _members(test_db, NEW) == {PASSED, WAITING}
    old = _run(test_db, OLD)
    assert old["status"] == "cancelled" and old["superseded_by_run_id"] == NEW
    assert _run(test_db, NEW)["supersedes_run_id"] == OLD
    assert _open_memberless(test_db, OLD) == []
    check = test_db.execute(
        "SELECT r.deployment_run_id,r.retracted_at,(SELECT count(*) FROM qa_runs q "
        "WHERE q.qa_requirement_id=r.id AND q.verdict='pass') AS passes "
        "FROM qa_requirements r WHERE r.id=%s",
        (run_check,),
    ).fetchone()
    assert check["retracted_at"] is None and check["passes"] == 0
    assert check["deployment_run_id"] == NEW
    assert (
        test_db.execute(
            "SELECT count(*) AS n FROM qa_requirements WHERE deployment_run_id=%s",
            (NEW,),
        ).fetchone()["n"]
        == 3
    )


@pytest.mark.parametrize("state", [containment.NOT_CONTAINED, containment.UNDETERMINED])
def test_a_candidate_not_containing_the_older_one_refuses(test_db, monkeypatch, state):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch, state)

    with pytest.raises(TakeoverRefused) as refused:
        take_over_waiting_run(test_db, NEW, session_id=DRIVER_SESSION)
    test_db.rollback()

    message = str(refused.value)
    assert NOT_CONTAINED_CODE in message and OLD_LINEAGE in message
    assert f"yoke deployment-runs remove-item {OLD} " in message
    assert _members(test_db, OLD) == {PASSED, WAITING}
    assert _run(test_db, OLD)["superseded_by_run_id"] is None


def test_another_sessions_live_driver_refuses(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)

    with pytest.raises(TakeoverRefused, match="takeover_run_driven_elsewhere"):
        take_over_waiting_run(test_db, NEW, session_id="someone-else")
    test_db.rollback()
    assert _members(test_db, OLD) == {PASSED, WAITING}


def test_the_unlocked_creation_pass_projects_members_then_rolls_back(
    test_db, monkeypatch
):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)

    assert take_over_waiting_run(test_db, NEW, apply=False) == OLD
    assert _members(test_db, OLD) == set()
    assert _members(test_db, NEW) == {PASSED, WAITING}
    assert _run(test_db, OLD)["status"] == "executing"
    assert removed_item_ids(test_db, OLD) == set()
    test_db.rollback()
    assert _members(test_db, OLD) == {PASSED, WAITING}
    assert _members(test_db, NEW) == set()
    assert _run(test_db, OLD)["superseded_by_run_id"] is None


def test_a_run_not_yet_at_item_qa_is_left_alone(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='deploy' WHERE id=%s", (OLD,)
    )
    _seed_new(test_db)
    _contains(monkeypatch)

    assert _take_over(test_db) is None
    assert _members(test_db, OLD) == {PASSED, WAITING}
    assert _run(test_db, NEW)["supersedes_run_id"] is None


@pytest.mark.parametrize("tail", ["auto", "command"])
def test_real_flow_final_completion_tail(test_db, monkeypatch, tail):
    """The item-QA cursor may precede final auto completion, never execution."""
    import json

    _seed_old(test_db, run_qa=False)
    stages = json.loads(
        test_db.execute(
            "SELECT stages FROM deployment_flows WHERE id=%s", (f"flow-{OLD}",)
        ).fetchone()[0]
    )
    stages.append({"name": "complete", "step_runner": tail, "stage_kind": "execution"})
    test_db.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (json.dumps(stages), f"flow-{OLD}"),
    )
    _close_passed(test_db)
    _seed_new(test_db)
    _contains(monkeypatch)
    assert _take_over(test_db) == (OLD if tail == "auto" else None)
    assert _members(test_db, NEW) == ({WAITING} if tail == "auto" else set())


def test_newest_live_run_wins_over_stale_failed_qa_without_restarting(
    test_db, monkeypatch
):
    from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    cases = _dated_target(test_db)
    stale = "run-aaa-failed"
    _dated_copy(test_db, stale, status="failed", created_at="2026-11-01T00:00:00Z",
                open_requirement=cases[WAITING])
    execution = begin_plan_execution(
        test_db, deployment_run_id=OLD, deployment_stage="item-qa",
        deployment_member_item_id=WAITING, actor_id="1", session_id=DRIVER_SESSION,
    )
    before = select_plan_execution(test_db, execution["id"], lock=False)
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD

    after = select_plan_execution(test_db, execution["id"], lock=False)
    assert after == {**before, "deployment_run_id": NEW}
    assert _run(test_db, NEW)["supersedes_run_id"] == OLD
    assert _run(test_db, stale)["superseded_by_run_id"] is None
    assert open_qa_lines(test_db, stale)


@pytest.mark.parametrize("newest_status", ["failed", "succeeded", "created"])
def test_only_newest_candidate_can_supply_qa(test_db, monkeypatch, newest_status):
    cases = _dated_target(test_db)
    stale = "run-aaa-failed"
    _dated_copy(test_db, stale, status="failed", created_at="2026-11-01T00:00:00Z",
                open_requirement=cases[WAITING])
    test_db.execute("UPDATE deployment_runs SET status=%s WHERE id=%s",
                    (newest_status, OLD))
    if newest_status == "created":
        test_db.execute("UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s",
                        (stale, OLD))
    _contains(monkeypatch)

    expected = OLD if newest_status in {"failed", "created"} else None
    assert _take_over(test_db) == expected
    assert _run(test_db, NEW)["supersedes_run_id"] == expected
    assert _run(test_db, stale)["superseded_by_run_id"] is None


def test_newest_never_started_run_is_taken_over_ahead_of_older_qa(test_db, monkeypatch):
    _dated_target(test_db)
    _dated_copy(test_db, "run-cancelled", status="cancelled",
                created_at="2026-11-03T00:00:00Z")
    _dated_copy(test_db, "run-never-started", status="created",
                created_at="2026-11-04T00:00:00Z")
    _contains(monkeypatch)

    assert _take_over(test_db) == "run-never-started"
    assert _run(test_db, NEW)["supersedes_run_id"] == "run-never-started"
