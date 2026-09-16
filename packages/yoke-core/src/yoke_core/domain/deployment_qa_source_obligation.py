"""Whether one intake source obligation is accepted on the completion run."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    acceptance_waived,
    latest_verdict,
    stage_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.schema_common import _table_exists


def latest_deployment_run_for_item(conn: Any, item_id: int) -> dict[str, str]:
    """Return the registered ``done_transition.latest_deployment_run`` binding.

    Empty ``run_id`` and ``status`` mean the item has no attached run.
    """
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return {"run_id": "", "status": ""}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT dr.id, dr.status FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        f"WHERE dri.item_id = {marker} "
        "ORDER BY dr.created_at DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if not row:
        return {"run_id": "", "status": ""}
    run_id = row["id"] if hasattr(row, "keys") else row[0]
    status = row["status"] if hasattr(row, "keys") else row[1]
    return {"run_id": str(run_id or ""), "status": str(status or "")}


def source_obligation_consumed(
    conn: Any, *, item_id: int, source_requirement_id: int
) -> bool:
    """True when this intake row's admitted copy is accepted on the completion run."""
    binding = latest_deployment_run_for_item(conn, int(item_id))
    run_id = binding["run_id"]
    if not run_id or binding["status"] != "succeeded":
        return False
    case_key = admitted_requirement_case_key(int(source_requirement_id))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id,deployment_stage,deployment_member_item_id "
        "FROM qa_requirements WHERE deployment_run_id="
        f"{marker} AND plan_case_key={marker} AND plan_id IS NULL "
        "ORDER BY id",
        (run_id, case_key),
    ).fetchall()
    if len(rows) != 1:
        return False
    row = rows[0]
    copy_id = int(row["id"] if hasattr(row, "keys") else row[0])
    stage_name = str(row["deployment_stage"] if hasattr(row, "keys") else row[1] or "")
    member = row["deployment_member_item_id"] if hasattr(row, "keys") else row[2]
    member_item_id = int(member) if member not in (None, 0) else None
    try:
        subject = deployment_qa_stage_subject(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            require_active=False,
        )
        target = deployment_qa_execution_target(conn, subject)
        blockers = stage_acceptance_blockers(
            conn,
            subject=subject,
            target=target,
            acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
        )
    except (LookupError, TypeError, ValueError):
        return False
    if blockers:
        return False
    if acceptance_waived(conn, copy_id):
        return True
    return latest_verdict(conn, copy_id) == "pass"


def blocking_row_unsatisfied_at_done(
    conn: Any,
    *,
    item_id: int,
    source_requirement_id: int,
    qa_phase: str,
    original_passed: bool,
) -> bool:
    """True when this blocking intake row still holds ``done``.

    A ``post_deploy`` row is answered by the admitted copy on the completion
    run and by nothing else -- ``original_passed`` is deliberately ignored for
    it. That row's own passing run was recorded against whatever candidate was
    deployed when it ran, so honouring it here would let a prior candidate's
    proof close out the release actually being delivered, which is the exact
    substitution frozen admission exists to prevent. An item with no succeeded
    completion run, or whose admitted copy is missing, rejected, or stale, has
    no such proof and keeps blocking.

    Every other phase keeps its established meaning, where the original row's
    own passing run is the satisfaction: pre-merge verification proves the
    branch, and manual acceptance proves itself.
    """
    if qa_phase != "post_deploy":
        return not original_passed
    return not source_obligation_consumed(
        conn, item_id=int(item_id), source_requirement_id=int(source_requirement_id)
    )


def row_unsatisfied_at_done(conn: Any, row: Any, *, item_id: int) -> bool:
    """:func:`blocking_row_unsatisfied_at_done` over a queried requirement row.

    The row carries ``id``, ``qa_phase``, and ``passed`` -- the last being
    whether the ORIGINAL requirement has any passing run. Callers select it
    rather than filtering on it in SQL, because a ``post_deploy`` row filtered
    out for having passed once is a row this predicate never gets to refuse.
    """
    if hasattr(row, "keys"):
        phase = str(row["qa_phase"] or "")
        source_id = int(row["id"])
        passed = bool(row["passed"])
    else:
        phase = str(row[1] or "")
        source_id = int(row[0])
        passed = bool(row[2])
    return blocking_row_unsatisfied_at_done(
        conn,
        item_id=int(item_id),
        source_requirement_id=source_id,
        qa_phase=phase,
        original_passed=passed,
    )


def unsatisfied_blocking_count(conn: Any, *, item_id: int, target_status: str) -> int:
    """How many of the item's blocking requirements are still unsatisfied.

    At ``done`` each row is answered by :func:`row_unsatisfied_at_done`, so a
    ``post_deploy`` row is judged on its completion-run admitted copy. At every
    other target the original row's own passing run is the answer.

    The requirement count keeps the blocking scan off databases with no QA rows
    at all, whose minimal schema need not carry every column that scan reads.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    present = conn.execute(
        f"SELECT COUNT(*) as cnt FROM qa_requirements WHERE item_id = {marker}",
        (int(item_id),),
    ).fetchone()
    if not (present["cnt"] if present else 0):
        return 0
    rows = conn.execute(
        "SELECT qr.id, qr.qa_phase, EXISTS("
        "SELECT 1 FROM qa_runs qrun "
        "WHERE qrun.qa_requirement_id = qr.id AND qrun.verdict = 'pass'"
        ") AS passed FROM qa_requirements qr "
        f"WHERE qr.item_id = {marker} AND qr.blocking_mode = 'blocking' "
        "AND qr.waived_at IS NULL",
        (int(item_id),),
    ).fetchall()
    if target_status != "done":
        return sum(1 for row in rows if not row["passed"])
    return sum(
        1 for row in rows if row_unsatisfied_at_done(conn, row, item_id=int(item_id))
    )


__all__ = [
    "blocking_row_unsatisfied_at_done",
    "latest_deployment_run_for_item",
    "row_unsatisfied_at_done",
    "source_obligation_consumed",
    "unsatisfied_blocking_count",
]
