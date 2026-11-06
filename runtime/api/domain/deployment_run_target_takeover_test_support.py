# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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


def _take_over(conn):
    taken = take_over_waiting_run(conn, NEW, session_id=DRIVER_SESSION, actor_id=1)
    conn.commit()
    return taken


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


def _dated_copy(conn, run_id, *, status, created_at, open_requirement=None):
    """Another run on this target, optionally owning open QA for a closed member."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,current_stage,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,release_lineage,"
        "%s,current_stage,%s FROM deployment_runs WHERE id=%s",
        (run_id, status, created_at, OLD),
    )
    if open_requirement is not None:
        requirement = _memberless_copy(conn, open_requirement)
        conn.execute(
            "UPDATE qa_requirements SET deployment_run_id=%s,"
            "deployment_member_item_id=%s WHERE id=%s",
            (run_id, PASSED, requirement),
        )
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
            "SELECT %s,%s,created_at FROM deployment_runs WHERE id=%s",
            (run_id, PASSED, run_id),
        )
    conn.commit()


def _dated_target(conn):
    cases = _seed_old(conn, run_qa=False)
    _close_passed(conn)
    conn.execute(
        "UPDATE deployment_runs SET created_at=%s WHERE id=%s",
        ("2026-11-02T00:00:00Z", OLD),
    )
    _seed_new(conn)
    conn.execute(
        "UPDATE deployment_runs SET created_at=%s WHERE id=%s",
        ("2026-11-06T00:00:00Z", NEW),
    )
    conn.commit()
    return cases
