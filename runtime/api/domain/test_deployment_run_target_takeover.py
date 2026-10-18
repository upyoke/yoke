"""Creating a run takes over an older run on its target that only waits on item QA."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain.deployment_run_target_takeover import (
    NOT_CONTAINED_CODE,
    TakeoverRefused,
    take_over_waiting_run,
)
from yoke_core.domain.deploy_target_occupancy import open_qa_lines

OLD = "run-takeover-old"
NEW = "run-takeover-new"
PASSED = 9971
WAITING = 9972
RUN_QA_STAGE = "run-qa"
OLD_LINEAGE = "b" * 40
NEW_LINEAGE = "c" * 40


def _requirement(conn, run_id, stage, member):
    member_sql = "IS NULL" if member is None else "= %s"
    params = (run_id, stage) + (() if member is None else (member,))
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        f"AND deployment_stage=%s AND deployment_member_item_id {member_sql} "
        "AND method_id IS NOT NULL ORDER BY id",
        params,
    ).fetchone()
    return int(row["id"])


def _seed_old(conn, *, run_qa: bool) -> dict[int, int]:
    """OLD stands on item QA with PASSED accepted and WAITING still open."""
    plan = create_smoke_plan(conn, project="yoke", slug=f"smoke-{OLD}")
    stages = item_qa_stage_definitions(plan)
    if run_qa:
        stages.append(
            {
                **stages[1],
                "name": RUN_QA_STAGE,
                "scope": "run",
            }
        )
    seed_run_standing_on_qa_stage(
        conn,
        run_id=OLD,
        project="yoke",
        stages=stages,
        members=(PASSED, WAITING),
        lineage=OLD_LINEAGE,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id IN (%s,%s)",
        (f"flow-{OLD}", PASSED, WAITING),
    )
    cases = {}
    for member in (PASSED, WAITING):
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=OLD,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=member,
        )
        cases[member] = _requirement(conn, OLD, ITEM_QA_STAGE, member)
    conn.commit()
    record_case_verdict(conn, cases[PASSED], "pass", evidence=True)
    return cases


def _close_passed(conn) -> None:
    """PASSED's accepted item QA closed it in the older run."""
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (PASSED,))
    conn.commit()


def _memberless_copy(conn, requirement_id: int, *, stage: str = ITEM_QA_STAGE) -> int:
    """A memberless copy of a case: a shared-plan copy, or a run-level check."""
    columns = [
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name NOT IN "
            "('id','deployment_member_item_id','deployment_stage')"
        ).fetchall()
    ]
    listed = ",".join(columns)
    row = conn.execute(
        f"INSERT INTO qa_requirements ({listed},deployment_stage) SELECT {listed},%s "
        "FROM qa_requirements WHERE id=%s RETURNING id",
        (stage, requirement_id),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _seed_new(conn, lineage: str = NEW_LINEAGE) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',created_at FROM deployment_runs WHERE id=%s",
        (NEW, lineage, OLD),
    )
    conn.commit()


def _contains(monkeypatch, state: str = containment.CONTAINED) -> None:
    monkeypatch.setattr(
        containment,
        "candidate_contains_commit",
        lambda *_a, **_k: containment.ContainmentVerdict(
            state, reason="" if state == containment.CONTAINED else "why"
        ),
    )


def _members(conn, run_id: str) -> set[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    return {int(row["item_id"]) for row in rows}


def _run(conn, run_id: str):
    return conn.execute(
        "SELECT status,superseded_by_run_id,supersedes_run_id FROM deployment_runs "
        "WHERE id=%s",
        (run_id,),
    ).fetchone()


def _open_memberless(conn, run_id: str) -> list:
    return conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id IS NULL AND retracted_at IS NULL "
        "AND waived_at IS NULL",
        (run_id,),
    ).fetchall()


def _take_over(conn):
    taken = take_over_waiting_run(conn, NEW, session_id=DRIVER_SESSION, actor_id=1)
    conn.commit()
    return taken


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
        "SELECT id,retracted_at FROM qa_requirements WHERE id IN (%s,%s)",
        (cases[WAITING], stranded),
    ).fetchall()
    assert all(row["retracted_at"] for row in retracted)
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
        "SELECT r.retracted_at,(SELECT count(*) FROM qa_runs q "
        "WHERE q.qa_requirement_id=r.id AND q.verdict='pass') AS passes "
        "FROM qa_requirements r WHERE r.id=%s",
        (run_check,),
    ).fetchone()
    assert check["retracted_at"] and check["passes"] == 0
    assert (
        test_db.execute(
            "SELECT count(*) AS n FROM qa_requirements WHERE deployment_run_id=%s",
            (NEW,),
        ).fetchone()["n"]
        == 0
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


def test_the_unlocked_creation_pass_only_asks_containment(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)

    assert take_over_waiting_run(test_db, NEW, apply=False) == OLD
    test_db.commit()
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
