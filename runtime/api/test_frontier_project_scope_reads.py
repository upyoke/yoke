"""The frontier reads dependency edges only for the projects it schedules."""

from __future__ import annotations

from yoke_core.domain.dependency_planning import evaluate_batch_gates
from yoke_core.domain.frontier import compute_frontier
from yoke_core.domain.frontier_compute import _project_scope_clause
from yoke_core.domain.frontier_depth import _compute_downstream_depths
from yoke_core.domain.frontier_sql import UNBLOCKS_COUNT_SQL
from runtime.api.frontier_test_helpers import (
    PROJECT_IDS,
    insert_dep,
    insert_item,
    make_test_db,
)

YOKE = PROJECT_IDS["yoke"]
OTHER = PROJECT_IDS["externalwebapp"]


def _two_projects():
    db = make_test_db()
    insert_item(db, 1, status="planned", workflow="epic")
    insert_item(db, 2, status="planned", workflow="epic")
    # A chain through another project's item still deepens this project's.
    insert_item(db, 20, status="planned", workflow="epic", project="externalwebapp")
    insert_dep(db, "YOK-20", "YOK-1")
    insert_dep(db, "YOK-2", "YOK-20")
    # Another project's own edges are none of this frontier's business.
    insert_item(db, 30, status="planned", workflow="epic", project="externalwebapp")
    insert_item(db, 31, status="planned", workflow="epic", project="externalwebapp")
    insert_dep(db, "YOK-31", "YOK-30")
    db.commit()
    return db


def test_depths_follow_only_chains_from_the_requested_project() -> None:
    db = _two_projects()

    depths = _compute_downstream_depths(db, _project_scope_clause(db, [YOKE]), [YOKE])

    assert depths[1] == 2
    assert 30 not in depths


def test_unblock_counts_read_only_the_requested_projects_blockers() -> None:
    db = _two_projects()
    cursor = db.cursor()
    cursor.execute(
        UNBLOCKS_COUNT_SQL.format(scope=_project_scope_clause(db, [YOKE])), (YOKE,)
    )

    assert {int(row[0]): int(row[1]) for row in cursor.fetchall()} == {1: 1}


def test_gate_evaluation_reads_only_the_requested_projects_dependents() -> None:
    db = _two_projects()

    everywhere = evaluate_batch_gates(db, "activation", emit_events=False)
    scoped = evaluate_batch_gates(
        db, "activation", emit_events=False, project_ids=[YOKE]
    )

    assert len(everywhere) == 3
    assert len(scoped) == 1
    assert set(scoped) < set(everywhere)


def test_scheduling_one_project_keeps_its_cross_project_chain() -> None:
    db = _two_projects()

    result = compute_frontier(db, project_scope=["yoke"], emit_events=False)

    by_id = {fi.item_id: fi for fi in result.runnable + result.blocked}
    assert by_id[1].downstream_depth == 2
    assert by_id[1].unblocks_count == 1
    assert {30, 31}.isdisjoint(by_id)
