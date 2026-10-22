"""What a plan refresh will not touch, and why it refuses rather than proceed.

Bringing a live requirement row back to its plan's current text is the one
supported correction. Two things can have frozen a copy of that row:

* a **live QA plan execution**, which built its roster from these rows. A
  case the walk has not reached takes the correction together with its
  roster entry; a reached case, a retired unreached case, or a case the
  refresh adds refuses and names the abort that reopens the walk
  (:mod:`qa_plan_execution_roster_correction`).
* an **admitted deployment-stage copy** of the row, frozen onto a run that is
  still executing. :mod:`qa_admitted_case_reconciliation` decides per copy
  whether the correction can honestly reach it, and
  :mod:`qa_admitted_copy_correction` carries it there; a copy the refresh
  leaves unchanged needs no decision at all.

A refusal raises inside the refresh's transaction, so the caller's rollback
leaves every row and roster exactly as it was. A half-applied refresh is the
state hardest to reason about afterwards.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import live_plan_execution_id, marker

LIVE_EXECUTION_CODE = "plan_execution_in_flight"

LIVE_EXECUTION_MESSAGE = (
    "{code}: {subject} is being walked by live QA plan execution "
    "{execution_id}, whose roster was frozen from these rows. Refreshing them "
    "now would move the definitions underneath a walk already in progress. "
    "Abort that execution with `{abort}`, then refresh and start the walk "
    "again — the abort is what makes the refresh reachable."
)


#: Subject columns that decide which refresh invocation reaches a row.
_REFRESH_SUBJECT_SQL = (
    "SELECT id,execution_target_json,item_id,deployment_run_id,deployment_stage,"
    "deployment_member_item_id,plan_id,workflow_transition_id "
    "FROM qa_requirements WHERE id="
)


def refresh_invocation(conn: Any, row: Any) -> str:
    """The one refresh command that reaches this row, by its own subject.

    An item row and a deployment row are refreshed by different subjects of
    the same operation, so naming one recipe for both would send half of all
    callers to a command that refuses them.
    """
    from yoke_core.domain.project_identity import render_item_ref

    if row["deployment_run_id"]:
        member = row["deployment_member_item_id"]
        if member is None and "execution_target_json" in row.keys():
            import json

            target = row["execution_target_json"]
            target = (
                target if isinstance(target, dict) else json.loads(str(target or "{}"))
            )
            if (target.get("deployment") or {}).get("shared_plan"):
                from yoke_core.domain.deployment_qa_shared_plans import (
                    requirement_subject,
                    group_members,
                )

                try:
                    group = requirement_subject(
                        conn, int(row["id"]), require_active=False
                    )
                except ValueError:
                    return ""
                members = group_members(conn, group, target)
                if not members:
                    return ""
                member = members[0]
        if (
            member is not None
            and query_one(
                conn,
                "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                (row["deployment_run_id"], member),
            )
            is None
        ):
            return ""
        subject = (
            f"--item {render_item_ref(conn, int(member))}"
            if member
            else f"--deployment-run-id {row['deployment_run_id']}"
        )
        return f"yoke qa plan rematerialize {subject} --stage {row['deployment_stage']}"
    if row["item_id"]:
        return (
            "yoke qa plan rematerialize --item "
            f"{render_item_ref(conn, int(row['item_id']))} "
            f"--transition {row['workflow_transition_id']}"
        )
    return ""


def refresh_recovery(conn: Any, row: Any) -> str:
    """The refresh sentence for a reader, or what to do when none reaches it."""
    invocation = refresh_invocation(conn, row)
    if invocation:
        return f"Refresh it from the plan with `{invocation}`."
    return (
        "No current refresh subject reaches this row (it may have lost its "
        "run membership or shared-plan owners); inspect its subject with "
        "`yoke qa requirement list`, then supersede it with "
        "`yoke qa requirement supersede` "
        "or waive it through the registered waiver surface."
    )


def plan_refresh_invocation(conn: Any, requirement_id: int) -> str:
    """The refresh that reaches this row from its plan, or ``""`` if none does.

    A row materialized from no plan has no plan to be refreshed from, so an
    empty answer is the honest one — naming a command that would refuse is
    exactly the failure this module exists to avoid.
    """
    row = query_one(
        conn, f"{_REFRESH_SUBJECT_SQL}{marker(conn)}", (int(requirement_id),)
    )
    if row is None or row["plan_id"] is None:
        return ""
    return refresh_invocation(conn, row)


def _abort_command(
    conn: Any,
    *,
    execution_id: str,
    item_id: Optional[int],
    deployment_run_id: Optional[str],
) -> str:
    """The execution identifies current ownership for abandonment."""
    return f'yoke qa plan abort --execution-id {execution_id} --reason "<why>"'


def carry_into_live_rosters(
    conn: Any,
    *,
    subject: str,
    rewritten: list[int],
    created: list[int],
    **live_subject: Any,
) -> None:
    """After a refresh's writes: correct unreached roster entries, or refuse.

    A created row would add a case the live walk's roster does not carry, so
    it refuses with the abort; rewritten and retired rows go to
    :func:`correct_live_rosters`, which reaches only cases not yet walked.
    """
    from yoke_core.domain.qa_plan_execution_roster_correction import (
        correct_live_rosters,
    )

    if created:
        require_no_live_execution(conn, subject=subject, **live_subject)
    correct_live_rosters(conn, rewritten)


def require_no_live_execution(
    conn: Any,
    *,
    subject: str,
    item_id: Optional[int] = None,
    transition_id: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    deployment_stage: Optional[str] = None,
    deployment_member_item_id: Optional[int] = None,
) -> None:
    """Refuse a refresh whose rows a live execution has already frozen in."""
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "qa_plan_executions"):
        return
    if deployment_stage and deployment_member_item_id is None:
        from yoke_core.domain.qa_stage_execution_holders import live_stage_executions

        # Every session's stage-wide walk froze rows from this subject.
        live = live_stage_executions(
            conn,
            deployment_run_id=str(deployment_run_id),
            deployment_stage=deployment_stage,
        )
        execution_id = str(live[0]["id"]) if live else None
    else:
        execution_id = live_plan_execution_id(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
        )
    if execution_id is None:
        return
    raise QaPlanError(
        LIVE_EXECUTION_MESSAGE.format(
            code=LIVE_EXECUTION_CODE,
            subject=subject,
            execution_id=execution_id,
            abort=_abort_command(
                conn,
                execution_id=execution_id,
                item_id=item_id,
                deployment_run_id=deployment_run_id,
            ),
        )
    )


__all__ = [
    "carry_into_live_rosters",
    "LIVE_EXECUTION_CODE",
    "LIVE_EXECUTION_MESSAGE",
    "plan_refresh_invocation",
    "refresh_invocation",
    "refresh_recovery",
    "require_no_live_execution",
]
