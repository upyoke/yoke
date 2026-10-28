"""Refresh pending deployment cases and their existing frozen selection atomically.

The subject is read first, unlocked; the run row lock covers only the writes,
after the projection's fingerprint proves that read still current. A run that
changed in between is read again unlocked, never under the lock.

A plan group (the memberless plan rows of an item-scoped stage) is never
refreshed: it runs its plan as the release pinned it, and an edited plan runs
on the next release.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_runs_lock import lock_current_read
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

PLAN_GROUP_REFRESH_REFUSAL = (
    "plan_group_not_rematerialized: deployment run {run_id!r} stage {stage!r} is "
    "item-scoped, so its run-wide plan rows are plan groups. A plan group runs "
    "its plan as the release pinned it; an edited plan runs on the next release. "
    "Correct a failed group case with `yoke qa plan run --deployment-run-id "
    "{run_id} --stage {stage} --plan P --replaces CASE_KEY=REQUIREMENT_ID`, or "
    "refresh one member's own plan cases with `yoke qa plan rematerialize "
    "--item PREFIX-N --stage {stage}`."
)


@presentation_operation
@run_presentation
def _read(conn: Any, *, run_id: str, stage: str, member: int | None, plan):
    """The projection and the subject this refresh writes, before any lock."""
    from yoke_core.domain.deployment_qa_materialization_projection import (
        MaterializationProjection,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        _run_stage,
        deployment_qa_stage_subject,
    )

    projection = MaterializationProjection(conn, run_id)
    if member is None:
        scope = _run_stage(conn, run_id, stage, require_active=False)["stage"]
        if str(scope.get("scope") or "") == "item":
            raise QaPlanError(PLAN_GROUP_REFRESH_REFUSAL.format(run_id=run_id, stage=stage))
    else:
        # Refuses an inactive stage or a departed member by name.
        deployment_qa_stage_subject(
            conn, run_id=run_id, stage_name=stage, member_item_id=member
        )
    return projection, read_subject_refresh(
        conn, run_id=run_id, stage=stage, member=member, plan=plan
    )


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

    _projection, refresh = lock_current_read(
        conn, run_id, read, holds=lambda current: current[0].holds(conn)
    )
    result = write_subject_refresh(conn, refresh)
    if commit:
        conn.commit()
    return {
        "deployment_run_id": run_id,
        "deployment_stage": stage,
        "deployment_member_item_id": deployment_member_item_id,
        **{
            key: sorted(set(result[key]))
            for key in (
                "plan_ids",
                "created_requirement_ids",
                "refreshed_requirement_ids",
                "waived_requirement_ids",
            )
        },
    }


__all__ = ["PLAN_GROUP_REFRESH_REFUSAL", "rematerialize_for_deployment_stage"]
