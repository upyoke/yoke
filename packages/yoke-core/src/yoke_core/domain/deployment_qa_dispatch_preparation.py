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
    rows = conn.execute(
        "SELECT DISTINCT deployment_member_item_id FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_stage=%s AND method_id IS NOT NULL",
        (run_id, str(stage["name"])),
    ).fetchall()
    existing = {
        row[0] if not hasattr(row, "keys") else row["deployment_member_item_id"]
        for row in rows
    }
    reads, errors = _read_missing(
        conn, stage, run_id=run_id, members=[m for m in members if m not in existing]
    )
    for member, read in reads.items():
        try:
            from yoke_core.domain.deployment_qa_stage_materialization import (
                materialize_deployment_qa_stage,
            )

            materialize_deployment_qa_stage(
                conn,
                deployment_run_id=run_id,
                deployment_stage=str(stage["name"]),
                deployment_member_item_id=member,
                prepared_read=read,
                advance_projection=True,
            )
        except (LookupError, ValueError) as exc:
            errors[member] = exc
    return errors
