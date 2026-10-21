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
def _read_missing(conn, stage, *, run_id, members):
    reads, errors = {}, {}
    for member in members:
        try:
            reads[member] = _read_member(conn, run_id, stage, member)
        except (LookupError, ValueError) as exc:
            errors[member] = exc
    return reads, errors


def prepare_members(conn, stage, *, run_id, members):
    """Materialize every member still owing cases; return per-member errors.

    The cohort is read as one set, unlocked, then written under one run lock.
    """
    from yoke_core.domain import deployment_qa_stage_materialization as materialization
    from yoke_core.domain.deployment_qa_materialization_write import (
        write_prepared_cohort,
    )

    rows = conn.execute(
        "SELECT DISTINCT deployment_member_item_id FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_stage=%s AND method_id IS NOT NULL",
        (run_id, str(stage["name"])),
    ).fetchall()
    existing = {
        row[0] if not hasattr(row, "keys") else row["deployment_member_item_id"]
        for row in rows
    }
    missing = [member for member in members if member not in existing]
    if not missing:
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
        read=lambda: _read_missing(conn, stage, run_id=run_id, members=missing),
        write=write,
    )
