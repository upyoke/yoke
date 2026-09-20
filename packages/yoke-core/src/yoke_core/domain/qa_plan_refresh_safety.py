"""What a plan refresh will not touch, and why it refuses rather than proceed.

Bringing a live requirement row back to its plan's current text is the one
supported correction, and it is safe exactly while nothing else has already
frozen a copy of that row. Two things can have:

* a **live QA plan execution**, which built its roster from these very rows
  and is being walked against it right now. Rewriting a row underneath that
  walk is the drift the roster snapshot check exists to catch, so the refresh
  refuses and names the abort that reopens it.
* an **admitted deployment-stage copy** of the row, frozen onto a run that is
  still executing. :mod:`qa_admitted_case_reconciliation` already decides per
  copy whether an amendment can honestly reach it; this asks it the same
  question before a refresh writes anything, rather than asking it a second
  way.

Both checks run before the first write, so a refused refresh leaves every row
exactly as it was. A half-applied refresh is the state hardest to reason about
afterwards, and it is the state that made the original defect invisible.
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
    "SELECT item_id,deployment_run_id,deployment_stage,"
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
        member_arg = (
            f" --member {render_item_ref(conn, int(member))}" if member else ""
        )
        return (
            "yoke qa plan rematerialize --deployment-run-id "
            f"{row['deployment_run_id']} --stage {row['deployment_stage']}"
            f"{member_arg}"
        )
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
        "This row names neither an item nor a deployment run, so no refresh "
        "subject reaches it; supersede it with `yoke qa requirement supersede` "
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
    """The abort invocation that actually reaches THIS execution.

    ``yoke qa plan abort`` takes a subject, the execution id and a reason, and
    refuses without all three. Naming the bare command would hand the reader a
    usage error instead of the recovery, so the subject is chosen from the
    same arguments the refusal was raised for.
    """
    from yoke_core.domain.project_identity import render_item_ref

    subject_flag = (
        f"--item {render_item_ref(conn, int(item_id))}"
        if item_id is not None
        else f"--deployment-run-id {deployment_run_id}"
    )
    return (
        f"yoke qa plan abort {subject_flag} --execution-id {execution_id} "
        '--reason "<why>"'
    )


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


def require_reachable_admitted_copies(
    conn: Any, requirement_ids: list[int]
) -> None:
    """Refuse a refresh that would strand a copy already frozen onto a run.

    A refresh rewrites the executable body whole, so every admitted copy of a
    refreshed row is affected by it. The reconciliation module owns which
    copies an amendment can reach; asking it here — before any write — is what
    keeps one answer for that question instead of two that can disagree.
    """
    from yoke_core.domain.qa_admitted_case_reconciliation import (
        admitted_copies_in_flight,
        unreachable_copy_refusal,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    refusals = []
    for requirement_id in requirement_ids:
        copies = admitted_copies_in_flight(conn, int(requirement_id))
        refusal = unreachable_copy_refusal(int(requirement_id), copies)
        if refusal:
            refusals.append(refusal)
    if refusals:
        raise QaPlanError(" ".join(refusals))


def correct_admitted_copies(
    conn: Any, *, source_requirement_id: int, definition: dict[str, Any]
) -> list[int]:
    """Carry a just-written refresh onto the copies frozen from this row.

    Refusing an unreachable copy is only half the answer. A copy that IS
    reachable would otherwise be left holding the pre-refresh body, and the
    stage walking it would then refuse as superseded — so the safe operation
    would have stranded the run it was meant to keep honest.

    The reconciliation module decides, per field and per copy, what may be
    written; this only hands it the fields the refresh actually changed.
    Anything admission rewrites for itself is outside that set by design.
    """
    from yoke_core.domain.qa_admitted_case_currency import DEFINITION_COLUMNS
    from yoke_core.domain.qa_admitted_case_reconciliation import (
        reconcile_admitted_copies,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    corrected: set[int] = set()
    for field in DEFINITION_COLUMNS:
        if field not in definition:
            continue
        reached, refusal = reconcile_admitted_copies(
            conn,
            source_requirement_id=int(source_requirement_id),
            field=field,
            value=definition[field],
        )
        if refusal:
            # The pre-pass cleared every copy before the first write, so a
            # refusal here means one answered or froze in between. Raising
            # keeps the caller's rollback the single outcome.
            raise QaPlanError(refusal)
        corrected.update(reached)
    return sorted(corrected)


__all__ = [
    "LIVE_EXECUTION_CODE",
    "LIVE_EXECUTION_MESSAGE",
    "correct_admitted_copies",
    "plan_refresh_invocation",
    "refresh_invocation",
    "refresh_recovery",
    "require_no_live_execution",
    "require_reachable_admitted_copies",
]
