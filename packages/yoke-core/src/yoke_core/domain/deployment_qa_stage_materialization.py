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


def _member_removed(conn: Any, run_id: str, member_item_id: int) -> LookupError:
    from yoke_core.domain.project_identity import render_item_ref

    return LookupError(
        f"deployment_member_removed: {render_item_ref(conn, member_item_id)} "
        f"is not an attached member of deployment run '{run_id}' while its QA is being prepared; "
        f"read `yoke deployment-runs get {run_id}` for the current members"
    )


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
        raise _member_removed(conn, run_id, member_item_id)


def removed_member_refusals(
    conn: Any, run_id: str, members: Any
) -> dict[int, LookupError]:
    """:func:`_require_member_still_attached` for a cohort, in one read."""
    wanted = sorted(int(member) for member in members if member is not None)
    if not wanted:
        return {}
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s)",
        (run_id, wanted),
    ).fetchall()
    attached = {int(row[0]) for row in rows}
    return {
        member: _member_removed(conn, run_id, member)
        for member in wanted
        if member not in attached
    }


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

    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    projection = presentation_read(
        conn,
        ("qa_materialization_projection", run_id),
        lambda: MaterializationProjection(conn, run_id),
    )
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
    prepared_read: _StageRead | None = None,
) -> dict[str, Any]:
    """Create each selected plan once for its source and deployed target.

    Every run-wide read happens first, unlocked and batched; the run row
    lock covers only the writes. A change committed in between is caught by
    the projection's fingerprint, and the lock is released while the read is
    repeated.
    """

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

    from yoke_core.domain.deployment_qa_materialization_write import (
        write_prepared_stage,
    )

    return write_prepared_stage(
        conn,
        prepared_read if prepared_read is not None else read(),
        reread=read,
        run_id=deployment_run_id,
        member=deployment_member_item_id,
        commit=commit,
        replaced_requirement_ids=replaced_requirement_ids,
    )


__all__ = ["QaCasesNotSelectedError", "materialize_deployment_qa_stage"]
