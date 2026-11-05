"""Prepare a dispatch cohort with one shared read snapshot before any writes."""

from yoke_core.domain.deployment_qa_stage_materialization import _read_stage
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation


def _read_member(conn, run_id, stage, member):
    return _read_stage(
        conn,
        run_id=run_id,
        deployment_stage=str(stage["name"]),
        deployment_member_item_id=member,
        agent_plan=None,
        replacement_keys=None,
        replaced_requirement_ids=frozenset(),
        replacement_scopes=None,
    )


@presentation_operation
@run_presentation
def _read_members(conn, stage, *, run_id, members):
    reads, errors = {}, {}
    for member in members:
        try:
            reads[member] = _read_member(conn, run_id, stage, member)
        except (LookupError, ValueError) as exc:
            errors[member] = exc
    return reads, errors


def prepare_members(conn, stage, *, run_id, members, then=None):
    """Materialize missing cases and stale member targets; return errors.

    The cohort is read as one set, unlocked, then written under one run lock,
    which ``then()`` (the stage's plan groups) shares.
    """
    from yoke_core.domain import deployment_qa_stage_materialization as materialization
    from yoke_core.domain.deployment_qa_materialization_write import (
        write_prepared_cohort,
        write_under_run_lock,
    )

    rows = conn.execute(
        "SELECT deployment_member_item_id,BOOL_OR("
        "superseded_by_requirement_id IS NULL AND retracted_at IS NULL "
        "AND execution_target_json IS NOT NULL AND execution_target_digest IS NOT NULL "
        "AND execution_target_json::jsonb #>> '{deployment,run_id}' IS DISTINCT FROM %s "
        "AND COALESCE(execution_target_json::jsonb #>> "
        "'{deployment,shared_plan,group_id}', '')='') AS stale_target "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND method_id IS NOT NULL GROUP BY deployment_member_item_id",
        (run_id, run_id, str(stage["name"])),
    ).fetchall()
    existing = {
        row[0] if not hasattr(row, "keys") else row["deployment_member_item_id"]: row[1]
        if not hasattr(row, "keys")
        else row["stale_target"]
        for row in rows
    }
    pending = [
        member for member in members if member not in existing or existing[member]
    ]
    if not pending:
        if then is not None:
            write_under_run_lock(conn, run_id, then)
        return {}

    def write(member, read):
        materialization.materialize_deployment_qa_stage(
            conn,
            deployment_run_id=run_id,
            deployment_stage=str(stage["name"]),
            deployment_member_item_id=member,
            prepared_read=read,
            commit=False,
        )

    return write_prepared_cohort(
        conn,
        run_id=run_id,
        read=lambda: _read_members(conn, stage, run_id=run_id, members=pending),
        write=write,
        then=then,
    )
