"""Refresh pending deployment cases and their existing frozen selection atomically.

A member's refresh covers each shared group it attaches plus its own plan
cases. Every subject is read first, unlocked and batched across the run's
members; the run row lock covers only the writes, after the projection's
fingerprint proves those reads still current.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_rematerialize_deployment_subject import (
    read_subject_refresh,
    write_subject_refresh,
)
from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.workflow_item_binding_lock import (
    rollback_workflow_binding_write_errors,
)


@presentation_operation
@run_presentation
def _read(conn: Any, *, run_id: str, stage: str, member: int | None, plan):
    """The projection and every subject this refresh writes, before any lock."""
    from yoke_core.domain.deployment_qa_materialization_projection import (
        MaterializationProjection,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    projection = MaterializationProjection(conn, run_id)
    own = dict(run_id=run_id, stage=stage, member=member, plan=plan)
    if member is None:
        return projection, [read_subject_refresh(conn, **own)]
    # Refuses an inactive stage or a departed member by name before any group.
    deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )
    groups = projection.member_groups(stage, member)
    if not groups:
        return projection, [read_subject_refresh(conn, **own)]
    refreshes = []
    for group in groups:
        selected = group.subject["shared_snapshot"]["plan"]
        if plan is not None and str(plan) not in {
            str(selected["id"]),
            str(selected["slug"]),
        }:
            continue
        refreshes.append(
            read_subject_refresh(
                conn,
                run_id=run_id,
                stage=stage,
                member=None,
                plan=selected["id"],
                shared_digest=group.digest,
                selection_member=member,
            )
        )
    has_own = conn.execute(
        "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND deployment_member_item_id=%s AND plan_id IS NOT NULL LIMIT 1",
        (run_id, stage, member),
    ).fetchone()
    # A named plan no shared group answers is this member's own: its refresh
    # narrows to that plan and checks only this member's walks.
    if has_own and (plan is None or not refreshes):
        refreshes.append(read_subject_refresh(conn, **own))
    if not refreshes:
        raise QaPlanError(
            "shared_plan_refresh_selection: selected plan is neither a shared plan "
            "this member attaches nor one of its own materialized plans; "
            "inspect this member's plans"
        )
    return projection, refreshes


@composition_operation
@rollback_workflow_binding_write_errors
def rematerialize_for_deployment_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    plan: str | int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Refresh this subject's plan cases from their current plan definitions."""
    run_id, stage = str(deployment_run_id), str(deployment_stage)

    def read():
        return _read(
            conn,
            run_id=run_id,
            stage=stage,
            member=deployment_member_item_id,
            plan=plan,
        )

    projection, refreshes = read()
    lock_run(conn, str(run_id))
    if not projection.holds(conn):
        projection, refreshes = read()
    results = [
        write_subject_refresh(
            conn,
            refresh,
            group_digests=lambda member: projection.digests(stage, member),
        )
        for refresh in refreshes
    ]
    if commit:
        conn.commit()
    return {
        "deployment_run_id": run_id,
        "deployment_stage": stage,
        "deployment_member_item_id": deployment_member_item_id,
        **{
            key: sorted({value for result in results for value in result[key]})
            for key in (
                "plan_ids",
                "created_requirement_ids",
                "refreshed_requirement_ids",
                "waived_requirement_ids",
            )
        },
    }


__all__ = ["rematerialize_for_deployment_stage"]
