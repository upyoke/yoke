"""Reach an in-flight admitted QA copy when a source row is amended, or refuse.

An item requirement corrected while a deployment run is still executing has
admitted copies out in the world (:mod:`deployment_qa_admission_materialization`),
and the amendment used to land on the source alone. This module decides, per
copy, which of the two honest outcomes applies -- never a silent third.

A copy on a **terminal** run is not here at all. It is the acceptance record
of what that release was judged against, and reaching into it would rewrite
history rather than correct a pending case.

A copy whose own obligation is already **settled** is not here either --
waived, or superseded by a corrected case that carries the obligation now
(:mod:`qa_obligation_settlement`). Nothing is still waiting on such a copy,
so it has no claim to hold its source row still. Honouring only the waiver
closed the exit the supersede receipt now names: the operator superseded the
frozen copy exactly as instructed, then found correcting the intake row
refused because of that same discharged copy, and the refusal sent them back
to supersede it again.

A copy on an **active** run that has not yet recorded a determinate verdict is
reached: the amendment is applied to it as well. That is not a new licence,
it is :mod:`qa_deployment_case_correction_window` applied to the copy -- until
a case has answered it is a case nobody has judged, so correcting it rewrites
no acceptance. That is what makes it safe mid-run.

A copy that has answered, or that a live execution has already frozen into the
roster it is being walked against, cannot be reached without rewriting
something real. So the amendment is refused **before any write**, naming the
copy, the run, and the recovery the operator can actually take.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_admission_materialization import (
    ADMITTED_REQUIREMENT_CASE_PREFIX,
)
from yoke_core.domain.qa_admitted_case_currency import (
    ANSWERED_COPY_RECOVERY,
    DEFINITION_COLUMNS,
    REACHABLE_FIELD_RECOVERY,
)
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdict,
)
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_execution_store import (
    live_plan_execution_id,
    marker,
)
from yoke_core.domain.runs import ACTIVE_RUN_STATUSES
from yoke_core.domain.schema_common import _table_exists

ADMITTED_COPY_IN_FLIGHT_CODE = "admitted_copy_in_flight"


@dataclass(frozen=True)
class AdmittedCopy:
    """One admitted copy of a source row, and whether it can still be reached."""

    requirement_id: int
    run_id: str
    stage: str
    member_item_id: int | None
    blocked_reason: str
    #: What to do about this copy instead. It differs by reason: an aborted
    #: execution can be re-walked against a corrected copy, while a copy that
    #: already answered is frozen for good and only supersession discharges it.
    recovery: str = ""

    @property
    def reachable(self) -> bool:
        return not self.blocked_reason


def _live_execution_holds(conn: Any, row: Any) -> bool:
    """True when a live execution is already walking this copy's subject.

    The roster of a live execution for this run, stage and member was built
    from exactly this scope's cases, so the copy is inside it. Rewriting the
    row underneath that walk is the drift its snapshot check exists to catch.
    """
    if not _table_exists(conn, "qa_plan_executions"):
        return False
    member = row["deployment_member_item_id"]
    return (
        live_plan_execution_id(
            conn,
            deployment_run_id=str(row["deployment_run_id"]),
            deployment_stage=str(row["deployment_stage"] or ""),
            deployment_member_item_id=int(member) if member is not None else None,
        )
        is not None
    )


def admitted_copies_in_flight(
    conn: Any, source_requirement_id: int
) -> list[AdmittedCopy]:
    """Every admitted copy of this source row on a run that is still active."""
    for table in ("qa_requirements", "deployment_runs"):
        if not _table_exists(conn, table):
            return []
    placeholder = marker(conn)
    statuses = ",".join([placeholder] * len(ACTIVE_RUN_STATUSES))
    rows = query_rows(
        conn,
        "SELECT q.id,q.deployment_run_id,q.deployment_stage,"
        "q.deployment_member_item_id FROM qa_requirements q "
        "JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
        f"WHERE q.plan_case_key={placeholder} AND q.plan_id IS NULL "
        f"AND NOT {settled_obligation_sql(conn, 'q')} "
        f"AND dr.status IN ({statuses}) "
        "ORDER BY q.id",
        (
            f"{ADMITTED_REQUIREMENT_CASE_PREFIX}{int(source_requirement_id)}",
            *sorted(ACTIVE_RUN_STATUSES),
        ),
    )
    copies: list[AdmittedCopy] = []
    for row in rows:
        copy_id = int(row["id"])
        verdict = determinate_verdict(conn, copy_id)
        if verdict:
            reason = (
                f"it has already recorded a {verdict} verdict, so its "
                "acceptance snapshot is frozen"
            )
            recovery = ANSWERED_COPY_RECOVERY.format(copy_id=copy_id)
        elif _live_execution_holds(conn, row):
            reason = (
                "a live QA execution has already frozen it into the roster it "
                "is being walked against"
            )
            recovery = REACHABLE_FIELD_RECOVERY
        else:
            reason, recovery = "", ""
        member = row["deployment_member_item_id"]
        copies.append(
            AdmittedCopy(
                requirement_id=copy_id,
                run_id=str(row["deployment_run_id"]),
                stage=str(row["deployment_stage"] or ""),
                member_item_id=int(member) if member is not None else None,
                blocked_reason=reason,
                recovery=recovery,
            )
        )
    return copies


def unreachable_copy_refusal(
    source_requirement_id: int, copies: list[AdmittedCopy]
) -> str:
    """The named refusal for copies this amendment cannot honestly reach."""
    blocked = [copy for copy in copies if not copy.reachable]
    if not blocked:
        return ""
    detail = "; ".join(
        f"admitted case {copy.requirement_id} on deployment run "
        f"{copy.run_id} stage {copy.stage!r} cannot be corrected because "
        f"{copy.blocked_reason} -- {copy.recovery}"
        for copy in blocked
    )
    return (
        f"{ADMITTED_COPY_IN_FLIGHT_CODE}: requirement "
        f"{int(source_requirement_id)} has been admitted to a deployment run "
        f"that is still executing, and {detail} Amending the item row alone "
        "would leave that run certifying a definition this item has already "
        "superseded."
    )


def reconcile_admitted_copies(
    conn: Any, *, source_requirement_id: int, field: str, value: Any
) -> tuple[list[int], str]:
    """Reach every reachable admitted copy, or report the refusal to raise.

    Returns the copies updated and an empty string, or an empty list and the
    named refusal. The caller checks the refusal **before** writing the
    source, so a refused amendment leaves both rows exactly as they were.

    A field outside :data:`DEFINITION_COLUMNS` reconciles nothing: admission
    rewrites ``target_env`` and ``qa_phase`` to the stage's own target by
    design, so copying an item's value over them would break the copy rather
    than correct it.
    """
    if field not in DEFINITION_COLUMNS:
        return [], ""
    copies = admitted_copies_in_flight(conn, int(source_requirement_id))
    if not copies:
        return [], ""
    refusal = unreachable_copy_refusal(int(source_requirement_id), copies)
    if refusal:
        return [], refusal
    placeholder = marker(conn)
    updated: list[int] = []
    for copy in copies:
        conn.execute(
            f"UPDATE qa_requirements SET {field} = {placeholder} "
            f"WHERE id = {placeholder}",
            (value, copy.requirement_id),
        )
        updated.append(copy.requirement_id)
    return updated, ""


__all__ = [
    "ADMITTED_COPY_IN_FLIGHT_CODE",
    "AdmittedCopy",
    "admitted_copies_in_flight",
    "reconcile_admitted_copies",
    "unreachable_copy_refusal",
]
