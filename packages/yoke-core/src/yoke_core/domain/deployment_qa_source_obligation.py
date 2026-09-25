"""Whether one intake source obligation is accepted on the completion run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow,
    membership_closes_item,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_run_bound_done_settlement import (
    superseded_run_bound_row_satisfied,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    latest_verdict,
    stage_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_run_bound_sources import BOUND_SOURCES_FIELD
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.schema_common import _column_exists, _table_exists

# Intake recovery wording is pinned in test_post_deploy_recovery_exit_conditions.py.
POST_DEPLOY_RECOVERY = (
    "A post_deploy obligation is satisfied by its admitted copy on the selected "
    "completion member; re-running intake cannot clear it. If no admitted copy "
    "was accepted because no final delivery or matching QA target exists, deliver "
    "the item through a flow whose stage target matches target_env and finish "
    "its required delivery and QA. If a corrected case bound to the same run, "
    "stage, member, and target already passed, use `yoke qa requirement "
    "supersede` for the defective copy; finished runs refuse new bound cases. "
    "If no correction can apply, waive the requirement through the registered "
    "surface with explicit authorization. Every admitted duplicate must be "
    "accepted, superseded, or waived. A failed run-bound case needs a passing "
    "same-run, stage, member, and target replacement with accepted stage proof "
    "or an authorized waiver; another delivery cannot settle it."
)


def latest_completion_run(
    conn: Any, item_id: int, *, skip_terminal_failures: bool = False
) -> dict[str, Any] | None:
    """Newest membership that can close this item, or none.

    Uses :func:`membership_closes_item` over newest-first memberships.

    Failed and cancelled attempts may be skipped for source QA; a newer active
    attempt still wins and must finish before that source can close out.

    Freshness is still ``created_at`` (then ``id``). ``release_lineage`` and
    ``project_id`` name the candidate to ask containment about: the commit
    the run recorded for THIS item's project, which for an own-project run
    is the run's own lineage and for a carrier is the bound commit.
    """
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return None
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT dr.id, dr.status, dr.current_stage, dr.project_id, "
        "COALESCE(dr.release_lineage, '') AS release_lineage, dr.flow, "
        "i.project_id AS item_project_id, "
        f"{_bound_sources_column(conn)} "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        "JOIN items i ON i.id = dri.item_id "
        f"WHERE dri.item_id = {marker} "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        (int(item_id),),
    ).fetchall()
    for row in rows:
        item_project = int(_row_value(row, "item_project_id", 6))
        source_sha = recorded_source_sha(
            {
                "project_id": _row_value(row, "project_id", 3),
                "release_lineage": _row_value(row, "release_lineage", 4),
                BOUND_SOURCES_FIELD: _row_value(row, BOUND_SOURCES_FIELD, 7),
            },
            item_project,
        )
        run_flow = str(_row_value(row, "flow", 5) or "")
        if not membership_closes_item(
            run_flow=run_flow,
            completion_flow=flow,
            run_project_id=int(_row_value(row, "project_id", 3)),
            item_project_id=item_project,
            source_sha=source_sha,
        ):
            continue
        status = str(_row_value(row, "status", 1) or "")
        if skip_terminal_failures and status in {"failed", "cancelled"}:
            continue
        return {
            "id": str(_row_value(row, "id", 0) or ""),
            "status": status,
            "current_stage": str(_row_value(row, "current_stage", 2) or ""),
            "project_id": item_project,
            "release_lineage": source_sha,
            "flow": run_flow,
        }
    return None


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _bound_sources_column(conn: Any) -> str:
    """Select the recorded bound sources, or empty on an unconverged plane."""
    if _column_exists(conn, "deployment_runs", BOUND_SOURCES_FIELD):
        return f"COALESCE(dr.{BOUND_SOURCES_FIELD}, '') AS {BOUND_SOURCES_FIELD}"
    return f"'' AS {BOUND_SOURCES_FIELD}"


def latest_deployment_run_for_item(conn: Any, item_id: int) -> dict[str, str]:
    """Return the registered ``done_transition.latest_deployment_run`` binding.

    Empty ``run_id`` and ``status`` mean the item has no completion-flow run.
    """
    row = latest_completion_run(conn, int(item_id))
    if row is None:
        return {"run_id": "", "status": ""}
    return {"run_id": row["id"], "status": row["status"]}


def source_obligation_consumed(
    conn: Any, *, item_id: int, source_requirement_id: int
) -> bool:
    """Require every admitted copy on the selected completion member to pass.

    Failed or cancelled members cannot mask prior success; a newer active
    member holds the wait. A later containment-only release has no QA copy.
    Zero copies is unmet. Stage acceptance and every copy's pass or discharge
    (waiver or supersession) are required. A bad replacement remains a stage
    blocker, and an unsettled duplicate still holds ``done``.
    """
    # Containment-only releases prove delivery, but have no member-scoped QA
    # copy. Read the completion membership that actually admitted this source.
    completion = latest_completion_run(conn, int(item_id), skip_terminal_failures=True)
    if completion is None:
        return False
    if completion["status"] != "succeeded":
        from yoke_core.domain.deployment_member_independent_close_out import (
            independent_member_delivery_ready,
        )

        if not independent_member_delivery_ready(
            conn, item_id=int(item_id), run_id=str(completion["id"])
        ):
            return False
    run_id = completion["id"]
    case_key = admitted_requirement_case_key(int(source_requirement_id))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id,deployment_stage,deployment_member_item_id,"
        f"waived_at,superseded_by_requirement_id,{requirement_retracted_at_select(conn)} "
        "FROM qa_requirements WHERE deployment_run_id="
        f"{marker} AND plan_case_key={marker} AND plan_id IS NULL "
        "ORDER BY id",
        (run_id, case_key),
    ).fetchall()
    if not rows:
        return False
    row = rows[0]
    stage_name = str(_row_value(row, "deployment_stage", 1) or "")
    member = _row_value(row, "deployment_member_item_id", 2)
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
    for row in rows:
        copy_id = int(_row_value(row, "id", 0))
        settled = obligation_settled(
            {
                "waived_at": _row_value(row, "waived_at", 3),
                "superseded_by_requirement_id": _row_value(
                    row, "superseded_by_requirement_id", 4
                ),
                "retracted_at": _row_value(row, "retracted_at", 5),
            }
        )
        if not settled and latest_verdict(conn, copy_id) != "pass":
            return False
    return True


def blocking_row_unsatisfied_at_done(
    conn: Any,
    *,
    item_id: int,
    source_requirement_id: int,
    qa_phase: str,
    original_passed: bool,
) -> bool:
    """True when this blocking intake row still holds ``done``.

    A ``post_deploy`` row needs its completion member's admitted proof; its
    own earlier pass could describe another candidate. Other phases keep
    their original passing run as proof.
    """
    if qa_phase != "post_deploy":
        return not original_passed
    return not source_obligation_consumed(
        conn, item_id=int(item_id), source_requirement_id=int(source_requirement_id)
    )


def row_unsatisfied_at_done(conn: Any, row: Any, *, item_id: int) -> bool:
    """:func:`blocking_row_unsatisfied_at_done` over a queried requirement row.

    Callers select the original row's own pass rather than filtering on it
    in SQL, so a ``post_deploy`` row that already passed is still judged.
    """
    if hasattr(row, "keys"):
        phase = str(row["qa_phase"] or "")
        source_id = int(row["id"])
        passed = bool(row["passed"])
        if row.get("item_id") is None:
            if phase == "post_deploy" and not passed and row["deployment_run_id"]:
                return not superseded_run_bound_row_satisfied(
                    conn,
                    requirement_id=source_id,
                    item_id=item_id,
                    completion=latest_completion_run(conn, item_id),
                )
            phase = ""
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


@dataclass(frozen=True)
class UnsatisfiedBlocking:
    """The item's still-unsatisfied blocking requirements, and their shape.

    ``includes_post_deploy`` is what a refusal needs in order to name the
    right recovery: a post_deploy row is cleared by delivery or by a waiver,
    never by executing the case again.
    """

    count: int = 0
    includes_post_deploy: bool = False
    rows: tuple[dict[str, Any], ...] = ()


def unsatisfied_blocking(
    conn: Any, *, item_id: int, target_status: str
) -> UnsatisfiedBlocking:
    """Which of the item's blocking requirements are still unsatisfied.

    At ``done`` each row is answered by :func:`row_unsatisfied_at_done`.
    Item-bound and member-scoped run-bound rows share
    :meth:`GateTarget.where_clause`; admitted copies are not independent.
    """
    from yoke_core.domain.qa_gate_definitions import (
        GateTarget,
        independent_item_obligation,
        status_settles_blocking_qa,
    )

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    where, params = GateTarget(item_id=int(item_id)).where_clause()
    if marker != "%s":
        where = where.replace("%s", marker)
    fetched = conn.execute(
        "SELECT qr.id, qr.qa_kind, qr.qa_phase, qr.deployment_run_id, "
        "qr.item_id, qr.plan_case_key "
        "FROM qa_requirements qr "
        f"WHERE {where} AND qr.blocking_mode = 'blocking' "
        "AND qr.waived_at IS NULL",
        params,
    ).fetchall()
    scored = []
    for row in fetched:
        item = dict(row)
        if not independent_item_obligation(item):
            continue
        item["passed"] = has_current_passing_run(conn, int(item["id"]))
        scored.append(item)
    if status_settles_blocking_qa(target_status):
        unsatisfied = [
            row
            for row in scored
            if row_unsatisfied_at_done(conn, row, item_id=int(item_id))
        ]
    else:
        unsatisfied = [row for row in scored if not row["passed"]]
    return UnsatisfiedBlocking(
        count=len(unsatisfied),
        includes_post_deploy=any(
            str(row["qa_phase"] or "") == "post_deploy" for row in unsatisfied
        ),
        rows=tuple(unsatisfied),
    )


__all__ = [
    "POST_DEPLOY_RECOVERY",
    "UnsatisfiedBlocking",
    "blocking_row_unsatisfied_at_done",
    "latest_completion_run",
    "latest_deployment_run_for_item",
    "row_unsatisfied_at_done",
    "source_obligation_consumed",
    "unsatisfied_blocking",
]
