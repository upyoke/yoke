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

A copy a live execution froze into its roster but has not reached yet is
reached too, together with its roster entry, so the walk runs it as corrected
(:mod:`qa_plan_execution_roster_correction`). A copy that has answered, or
that the walk has already reached, cannot be reached without rewriting
something real. So the amendment is refused **before any write**, naming the
copy, the run, and the recovery the operator can actually take.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.qa_admitted_case_currency import (
    ANSWERED_COPY_RECOVERY,
    DEFINITION_COLUMNS,
    REACHABLE_FIELD_RECOVERY,
    definition_value,
)
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdict,
)
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_execution_store import marker
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
    """True when a live execution's walk has already reached this copy.

    A copy the walk has not reached yet is still a case nobody has judged:
    the correction reaches it and its roster entry together
    (:mod:`qa_plan_execution_roster_correction`). A reached one is part of
    what the walk judged, so rewriting it would move evidence.
    """
    from yoke_core.domain.qa_plan_execution_roster_correction import (
        reached_by_live_execution,
    )

    return reached_by_live_execution(conn, int(row["id"])) is not None


def admitted_copies_in_flight(
    conn: Any, source_requirement_id: int
) -> list[AdmittedCopy]:
    """Every admitted copy of this source row on a run that is still active."""
    for table in ("qa_requirements", "deployment_runs"):
        if not _table_exists(conn, table):
            return []
    placeholder = marker(conn)
    source = query_one(
        conn,
        f"SELECT id,item_id FROM qa_requirements WHERE id={placeholder}",
        (int(source_requirement_id),),
    )
    if source is None or source["item_id"] is None:
        return []
    statuses = ",".join([placeholder] * len(ACTIVE_RUN_STATUSES))
    rows = query_rows(
        conn,
        "SELECT q.id,q.deployment_run_id,q.deployment_stage,"
        "q.deployment_member_item_id FROM qa_requirements q "
        "JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
        f"WHERE q.plan_id IS NULL AND q.plan_case_key={placeholder} "
        "AND q.deployment_member_item_id IS NOT NULL "
        f"AND NOT {settled_obligation_sql(conn, 'q')} "
        f"AND dr.status IN ({statuses}) ORDER BY q.id",
        (
            admitted_requirement_case_key(int(source_requirement_id)),
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
                "a live QA execution has already reached it in the roster it "
                "is being walked against"
            )
            recovery = REACHABLE_FIELD_RECOVERY
        else:
            reason, recovery = "", ""
        copies.append(
            AdmittedCopy(
                requirement_id=copy_id,
                run_id=str(row["deployment_run_id"]),
                stage=str(row["deployment_stage"] or ""),
                member_item_id=int(row["deployment_member_item_id"]),
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
    copies = [
        copy
        for copy in admitted_copies_in_flight(conn, int(source_requirement_id))
        if not _already_holds(conn, copy.requirement_id, field, value)
    ]
    if not copies:
        return [], ""
    refusal = unreachable_copy_refusal(int(source_requirement_id), copies)
    if refusal:
        return [], refusal
    from yoke_core.domain.qa_plan_execution_roster_correction import (
        correct_live_rosters,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    update = (
        f"UPDATE qa_requirements SET {field}={marker(conn)} WHERE id={marker(conn)}"
    )
    before = {
        copy.requirement_id: _field_value(conn, copy.requirement_id, field)
        for copy in copies
    }
    for copy_id in before:
        conn.execute(update, (value, copy_id))
    try:
        correct_live_rosters(conn, list(before))
    except QaPlanError as exc:
        # A live roster could not take the correction: put the copies back
        # and return the refusal; the caller does not commit a refused write.
        for copy_id, previous in before.items():
            conn.execute(update, (previous, copy_id))
        return [], str(exc)
    return list(before), ""


def _field_value(conn: Any, copy_id: int, field: str) -> Any:
    return query_one(
        conn,
        f"SELECT {field} FROM qa_requirements WHERE id={marker(conn)}",
        (int(copy_id),),
    )[field]


def _already_holds(conn: Any, copy_id: int, field: str, value: Any) -> bool:
    """True when the copy already carries ``value``: nothing to reach.

    An answered copy whose field is unchanged blocks nothing; only a copy the
    amendment would actually rewrite has to be reachable.
    """
    current = _field_value(conn, copy_id, field)
    return definition_value(field, current) == definition_value(field, value)


__all__ = [
    "ADMITTED_COPY_IN_FLIGHT_CODE",
    "AdmittedCopy",
    "admitted_copies_in_flight",
    "reconcile_admitted_copies",
    "unreachable_copy_refusal",
]
