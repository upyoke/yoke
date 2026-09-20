"""Whether one intake source obligation is accepted on the completion run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
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
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.schema_common import _column_exists, _table_exists

# A post_deploy row that already passed once is not re-runnable into
# satisfaction, so "execute the case" is the wrong instruction and
# "permanently blocked" is wrong too: there are three real ways out, and
# none of them is another run of the intake row.
POST_DEPLOY_RECOVERY = (
    "A post_deploy obligation is satisfied by the completion run's admitted "
    "copy, so re-running the intake row cannot clear it. Deliver the item "
    "through a flow whose stage target matches the requirement's target_env "
    "so the run admits and accepts it, correcting whichever of the two is "
    "wrong when they disagree; or, when the admitted copy was itself "
    "defective and already recorded a verdict, record a corrected case that "
    "passed in its place with yoke qa requirement supersede; or waive the "
    "requirement through the registered waiver surface with explicit "
    "authorization."
)


def latest_completion_run(conn: Any, item_id: int) -> dict[str, Any] | None:
    """Newest membership that can close this item, or none.

    Two memberships can: a run of the item's own selected completion flow,
    and a run of another project that ships this project's source — the
    carrier resolved this project's commit at start, so it delivers the
    item's merge as surely as the item's own flow would. A later carrying
    run of an unrelated flow in this project still does not.

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
        carried = int(_row_value(row, "project_id", 3)) != item_project
        if run_flow != flow and not (carried and source_sha):
            continue
        return {
            "id": str(_row_value(row, "id", 0) or ""),
            "status": str(_row_value(row, "status", 1) or ""),
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
    """True when this intake row's admitted copy is accepted on the completion run.

    "Accepted" is the stage's own answer plus the copy's own discharge state,
    and both discharge records count: a waiver and a supersession each settle
    the obligation without evidence from the copy itself. Honouring only the
    waiver made the product prescribe a remedy it then refused to read --
    the freeze refusal tells an owner to supersede a case that answered
    wrongly, the stage accepts the replacement, and ``done`` kept blocking on
    the frozen row anyway, leaving a waiver as the only exit.

    Following the link cannot launder a failure through. The replacement is
    bound to the same run, stage, member and execution target, so it is
    inside the scope :func:`stage_acceptance_blockers` already graded above
    on its own evidence: a replacement that is not passing leaves blockers,
    and this returns ``False`` before the discharge is ever consulted. An
    un-superseded failing copy is untouched and still holds ``done``.
    """
    binding = latest_deployment_run_for_item(conn, int(item_id))
    run_id = binding["run_id"]
    if not run_id or binding["status"] != "succeeded":
        return False
    case_key = admitted_requirement_case_key(int(source_requirement_id))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id,deployment_stage,deployment_member_item_id,"
        "waived_at,superseded_by_requirement_id "
        "FROM qa_requirements WHERE deployment_run_id="
        f"{marker} AND plan_case_key={marker} AND plan_id IS NULL "
        "ORDER BY id",
        (run_id, case_key),
    ).fetchall()
    if len(rows) != 1:
        return False
    row = rows[0]
    copy_id = int(_row_value(row, "id", 0))
    stage_name = str(_row_value(row, "deployment_stage", 1) or "")
    member = _row_value(row, "deployment_member_item_id", 2)
    member_item_id = int(member) if member not in (None, 0) else None
    settled = obligation_settled(
        {
            "waived_at": _row_value(row, "waived_at", 3),
            "superseded_by_requirement_id": _row_value(
                row, "superseded_by_requirement_id", 4
            ),
        }
    )
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
    if settled:
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


@dataclass(frozen=True)
class UnsatisfiedBlocking:
    """The item's still-unsatisfied blocking requirements, and their shape.

    ``includes_post_deploy`` is what a refusal needs in order to name the
    right recovery: a post_deploy row is cleared by delivery or by a waiver,
    never by executing the case again.
    """

    count: int = 0
    includes_post_deploy: bool = False


def unsatisfied_blocking(
    conn: Any, *, item_id: int, target_status: str
) -> UnsatisfiedBlocking:
    """Which of the item's blocking requirements are still unsatisfied.

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
        return UnsatisfiedBlocking()
    rows = conn.execute(
        "SELECT qr.id, qr.qa_phase FROM qa_requirements qr "
        f"WHERE qr.item_id = {marker} AND qr.blocking_mode = 'blocking' "
        "AND qr.waived_at IS NULL",
        (int(item_id),),
    ).fetchall()
    scored = []
    for row in rows:
        item = dict(row)
        item["passed"] = has_current_passing_run(conn, int(item["id"]))
        scored.append(item)
    rows = scored
    if target_status != "done":
        unsatisfied = [row for row in rows if not row["passed"]]
    else:
        unsatisfied = [
            row
            for row in rows
            if row_unsatisfied_at_done(conn, row, item_id=int(item_id))
        ]
    return UnsatisfiedBlocking(
        count=len(unsatisfied),
        includes_post_deploy=any(
            str(row["qa_phase"] or "") == "post_deploy" for row in unsatisfied
        ),
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
