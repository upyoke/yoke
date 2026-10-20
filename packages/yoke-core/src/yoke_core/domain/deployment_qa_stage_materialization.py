"""Materialize private cases and shared plan groups for deployment QA."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.schema_read_scope import composition_operation


class QaCasesNotSelectedError(QaPlanError):
    """No cases are selected for this stage subject yet.

    Deliberately its own type, because it is the ONLY materialization
    refusal that describes work an agent has not done rather than a
    definition that is wrong. The default story is that a stage names no
    cases and the responsible agent chooses or creates them, so a caller
    must be able to tell "nobody has selected cases yet" — a durable wait
    that should wake that agent — from an invalid pinned plan, an
    unresolvable target identity, or a permission failure, all of which
    are real stage failures. Collapsing them would either strand the
    agent or dress a broken definition up as patience.
    """


def _require_member_still_attached(
    conn: Any, run_id: str, member_item_id: int | None
) -> None:
    """Refuse by name when a removal committed while plans were being selected.

    Removal locks the run row too, so membership read under that lock holds
    until this transaction ends.
    """
    if member_item_id is None:
        return
    attached = conn.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, member_item_id),
    ).fetchone()
    if attached is None:
        from yoke_core.domain.project_identity import render_item_ref

        raise LookupError(
            f"deployment_member_removed: {render_item_ref(conn, member_item_id)} "
            f"left deployment run '{run_id}' while its QA was being prepared; "
            f"read `yoke deployment-runs get {run_id}` for the current members"
        )


@dataclass
class _StageRead:
    """Everything the write needs, read unlocked as one set for the run."""

    projection: Any
    subject: dict
    target: dict
    admitted: list
    snapshots: list
    # (snapshot, group subject, group target, members attaching the group)
    shared: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    private: list = field(default_factory=list)
    private_snapshots: list = field(default_factory=list)
    # Whether a member owing no case withdrew every group it still owed.
    withdrawn_discharge: bool | None = None


def _plans_with_member_copies(conn, run_id, stage, plan_ids) -> set[int]:
    """Shared plans whose unsettled member copies a group write would retire."""
    from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql

    if not plan_ids:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT q.plan_id FROM qa_requirements q WHERE q.deployment_run_id=%s "
        "AND q.deployment_stage=%s AND q.plan_id=ANY(%s) "
        f"AND q.deployment_member_item_id IS NOT NULL AND NOT {settled_obligation_sql(conn, 'q')}",
        (run_id, str(stage), sorted(set(plan_ids))),
    ).fetchall()
    return {int(row["plan_id"]) for row in rows}


@presentation_operation
@run_presentation
def _read_stage(
    conn: Any,
    *,
    run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None,
    agent_plan: str | None,
    replacement_keys: set[str] | None,
    replaced_requirement_ids: frozenset[int],
    replacement_scopes: dict[str, list[dict]] | None,
) -> _StageRead:
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
    from yoke_core.domain.deployment_qa_materialization_projection import (
        MaterializationProjection,
    )
    from yoke_core.domain.deployment_qa_plan_selection import selected_plans
    from yoke_core.domain.deployment_qa_shared_corrections import correction_subjects
    from yoke_core.domain.deployment_qa_shared_plans import shared_subject
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    projection = MaterializationProjection(conn, run_id)
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
    )
    target = deployment_qa_execution_target(conn, subject)
    admitted = member_requirements(conn, subject, target=target)
    snapshots = (
        [subject["shared_snapshot"]]
        if subject.get("shared_plan")
        else selected_plans(
            conn,
            subject,
            agent_plan=agent_plan,
            target=target,
            admitted=admitted,
            allow_empty=True,
            replacement_keys=replacement_keys,
            replacement_scopes=replacement_scopes,
        )
    )
    read = _StageRead(projection, subject, target, admitted, snapshots)
    if not snapshots and not any(r.get("method_id") for r in admitted):
        from yoke_core.domain.deployment_qa_shared_copy_reads import (
            withdrawn_member_discharge,
        )

        read.withdrawn_discharge = withdrawn_member_discharge(conn, subject, target)
    shared = projection.shareable(subject, target, snapshots)
    if not shared:
        return read
    copied = _plans_with_member_copies(
        conn, run_id, deployment_stage, [int(s["plan"]["id"]) for s in shared]
    )
    for snapshot in shared:
        group = shared_subject(subject, target, snapshot)
        group_target = deployment_qa_execution_target(conn, group)
        # Only a plan with member copies left to retire asks every member.
        members = (
            projection.group_members(group, group_target)
            if int(snapshot["plan"]["id"]) in copied
            else []
        )
        read.shared.append((snapshot, group, group_target, members))
    read.private = [
        r for r in admitted if r.get("plan_id") is None and r.get("method_id")
    ]
    corrections, read.private_snapshots = correction_subjects(
        conn,
        subject,
        [snapshot for snapshot in snapshots if snapshot not in shared],
        replaced_requirement_ids,
        projection=projection,
    )
    read.corrections = [
        (group, deployment_qa_execution_target(conn, group), snapshot)
        for group, snapshot in corrections
    ]
    return read


@composition_operation
def materialize_deployment_qa_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    agent_plan: str | None = None,
    commit: bool = True,
    replacement_keys: set[str] | None = None,
    replaced_requirement_ids: frozenset[int] = frozenset(),
    replacement_scopes: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """Create each selected plan once for its source and deployed target.

    Every run-wide read happens first, unlocked and batched; the run row
    lock covers only the writes. A change committed in between is caught by
    the projection's fingerprint and the read is repeated under the lock.
    """
    from yoke_core.domain.deployment_qa_shared_duplicates import retire_member_copies
    from yoke_core.domain.deployment_qa_snapshot_selection import freeze_selected_plans
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )

    def read() -> _StageRead:
        return _read_stage(
            conn,
            run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
            agent_plan=agent_plan,
            replacement_keys=replacement_keys,
            replaced_requirement_ids=replaced_requirement_ids,
            replacement_scopes=replacement_scopes,
        )

    stage_read = read()
    try:
        conn.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (deployment_run_id,),
        )
        _require_member_still_attached(
            conn, deployment_run_id, deployment_member_item_id
        )
        if not stage_read.projection.holds(conn):
            stage_read = read()
        subject, target = stage_read.subject, stage_read.target
        freeze_selected_plans(conn, subject, stage_read.snapshots)

        def write(group, group_target, admitted, snapshots):
            return materialize_subject(
                conn,
                subject=group,
                target=group_target,
                admitted=admitted,
                snapshots=snapshots,
                commit=False,
                replaced_requirement_ids=replaced_requirement_ids,
            )

        if not stage_read.shared:
            result = materialize_subject(
                conn,
                subject=subject,
                target=target,
                admitted=stage_read.admitted,
                snapshots=stage_read.snapshots,
                commit=False,
                replaced_requirement_ids=replaced_requirement_ids,
                withdrawn_discharge=stage_read.withdrawn_discharge,
            )
        else:
            results = []
            for snapshot, group, group_target, members in stage_read.shared:
                results.append(write(group, group_target, [], [snapshot]))
                retire_member_copies(
                    conn,
                    group,
                    group_target,
                    [
                        *results[-1]["created_requirement_ids"],
                        *results[-1]["existing_requirement_ids"],
                    ],
                    members=members,
                )
            for group, group_target, snapshot in stage_read.corrections:
                results.append(write(group, group_target, [], [snapshot]))
            if stage_read.private or stage_read.private_snapshots:
                results.append(
                    write(
                        subject,
                        target,
                        stage_read.private,
                        stage_read.private_snapshots,
                    )
                )
            result = {
                **results[0],
                "deployment_member_item_id": deployment_member_item_id,
                "created_requirement_ids": [
                    r for part in results for r in part["created_requirement_ids"]
                ],
                "existing_requirement_ids": [
                    r for part in results for r in part["existing_requirement_ids"]
                ],
            }
        if commit:
            conn.commit()
        return result
    except Exception:
        if commit:
            conn.rollback()
        raise


__all__ = ["QaCasesNotSelectedError", "materialize_deployment_qa_stage"]
