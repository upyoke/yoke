"""Carry a plan refresh onto the run-bound copies admitted from its rows.

A refreshed item requirement may have copies frozen onto deployment runs
that are still executing. Each run's shared groups are read before its row
lock; the lock then covers only the owner checks and corrections.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one


def lock_admitted_copies(conn: Any, requirement_ids: list[int]) -> dict[str, Any]:
    """Lock the runs holding these rows' admitted copies, then check owners.

    Locking before the first write keeps a run from answering or admitting
    in between. Whether each copy can take the correction is decided when
    its new value is known (:func:`correct_admitted_copies`): a copy the
    refresh leaves unchanged blocks nothing, even when it has answered.
    Each run's shared groups are read before its lock; the returned
    projections carry them to :func:`correct_admitted_copies`.
    """
    from yoke_core.domain.qa_admitted_case_reconciliation import (
        admitted_copies_in_flight,
    )

    copies = [
        copy
        for requirement_id in requirement_ids
        for copy in admitted_copies_in_flight(conn, int(requirement_id))
    ]
    run_ids = sorted({copy.run_id for copy in copies})
    # Every run is read before any run is locked, then locked in id order.
    reads = {run_id: _read_projection(conn, run_id) for run_id in run_ids}
    projections: dict[str, Any] = {}
    for run_id in run_ids:
        query_one(
            conn, "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,)
        )
    for run_id in run_ids:
        projection = reads[run_id]
        if not projection.holds(conn):
            projection = _read_projection(conn, run_id)
        projections[run_id] = projection
    for requirement_id in requirement_ids:
        for copy in admitted_copies_in_flight(conn, int(requirement_id)):
            _correct_selected_copy(
                conn,
                requirement_id,
                copy.requirement_id,
                write=False,
                projections=projections,
            )
    return projections


def _read_projection(conn, run_id):
    """The run's shared groups at every stage holding its requirements."""
    from yoke_core.domain.deployment_qa_materialization_projection import (
        read_run_projection,
    )

    stages = [
        row["deployment_stage"]
        for row in conn.execute(
            "SELECT DISTINCT deployment_stage FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_stage IS NOT NULL",
            (run_id,),
        ).fetchall()
    ]
    return read_run_projection(conn, run_id=run_id, stages=stages)


def _locked_projection(conn, projections, run_id):
    """A run first reached by a copy written in this refresh: read, then lock."""
    if run_id in projections:
        return projections[run_id]
    projection = _read_projection(conn, run_id)
    query_one(conn, "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))
    if not projection.holds(conn):
        projection = _read_projection(conn, run_id)
    projections[run_id] = projection
    return projection


def _correct_selected_copy(conn, source_id, copy_id, *, write, projections):
    from yoke_core.domain.deployment_qa_snapshot_correction import (
        selected_plan_owners,
        refresh_selected_cases,
    )
    from yoke_core.domain.qa_plan_case_definition import plan_cases
    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan
    from yoke_core.domain.qa_plan_management import _plan_row

    row = query_one(
        conn,
        "SELECT q.plan_id,q.plan_case_key,q.deployment_run_id,q.deployment_stage,"
        "q.execution_target_json,q.execution_target_digest,"
        "s.item_id FROM qa_requirements q JOIN qa_requirements s ON s.id=%s "
        "WHERE q.id=%s",
        (source_id, copy_id),
    )
    if row["plan_id"] is None:
        return
    require_candidate_plan(
        conn, _plan_row(conn, row["plan_id"]), row["deployment_run_id"]
    )
    scope = dict(
        run_id=row["deployment_run_id"],
        stage=row["deployment_stage"],
        plan_id=row["plan_id"],
        member_item_id=row["item_id"],
    )
    import json

    target = row["execution_target_json"]
    target = target if isinstance(target, dict) else json.loads(str(target or "{}"))
    if (target.get("deployment") or {}).get("shared_plan"):
        projection = _locked_projection(conn, projections, row["deployment_run_id"])
        scope["shared_target_digest"] = row["execution_target_digest"]
        scope["group_digests"] = lambda member: projection.digests(
            row["deployment_stage"], member
        )
    if not write:
        selected_plan_owners(conn, **scope)
        return
    cases = [
        case
        for case in plan_cases(conn, row["plan_id"])
        if case["case_key"] == row["plan_case_key"]
    ]
    refresh_selected_cases(conn, **scope, cases=cases)


def correct_admitted_copies(
    conn: Any,
    *,
    source_requirement_id: int,
    definition: dict[str, Any],
    projections: dict[str, Any],
) -> list[int]:
    """Carry a just-written refresh onto the copies frozen from this row.

    Refusing an unreachable copy is only half the answer. A copy that IS
    reachable would otherwise be left holding the pre-refresh body, and the
    stage walking it would then refuse as superseded — so the safe operation
    would have stranded the run it was meant to keep honest.

    The reconciliation module decides, per field and per copy, what may be
    written; this only hands it the fields the refresh actually changed.
    Anything admission rewrites for itself is outside that set by design.
    """
    from yoke_core.domain.qa_admitted_case_currency import DEFINITION_COLUMNS
    from yoke_core.domain.qa_admitted_case_reconciliation import (
        reconcile_admitted_copies,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    corrected: set[int] = set()
    for field in DEFINITION_COLUMNS:
        if field not in definition:
            continue
        reached, refusal = reconcile_admitted_copies(
            conn,
            source_requirement_id=int(source_requirement_id),
            field=field,
            value=definition[field],
        )
        if refusal:
            # Raising keeps the caller's rollback the single outcome.
            raise QaPlanError(refusal)
        corrected.update(reached)
    for copy_id in sorted(corrected):
        _correct_selected_copy(
            conn,
            source_requirement_id,
            copy_id,
            write=True,
            projections=projections,
        )
    return sorted(corrected)


__all__ = ["correct_admitted_copies", "lock_admitted_copies"]
