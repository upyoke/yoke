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
    admitted_requirement_identity_clause,
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
        "SELECT id,item_id,plan_id,plan_case_key,host_baseline,target_env,qa_phase "
        f"FROM qa_requirements WHERE id={placeholder}",
        (int(source_requirement_id),),
    )
    if source is None or source["item_id"] is None:
        return []
    identity = f"q.plan_id IS NULL AND q.plan_case_key={placeholder}"
    identity_params: tuple[Any, ...] = (
        admitted_requirement_case_key(int(source_requirement_id)),
    )
    if source["plan_id"] is not None and source["qa_phase"] == "post_deploy":
        plan_identity, plan_params = admitted_requirement_identity_clause(
            dict(source), marker=placeholder
        )
        identity = (
            f"({identity}) OR ({plan_identity} "
            f"AND (q.deployment_member_item_id={placeholder} OR q.deployment_member_item_id IS NULL) "
            f"AND q.host_baseline IS NOT DISTINCT FROM {placeholder} "
            f"AND (CAST({placeholder} AS TEXT) IS NULL OR q.target_env={placeholder}))"
        )
        identity_params += (
            *plan_params,
            int(source["item_id"]),
            source["host_baseline"],
            source["target_env"],
            source["target_env"],
        )
    statuses = ",".join([placeholder] * len(ACTIVE_RUN_STATUSES))
    rows = query_rows(
        conn,
        "SELECT q.id,q.deployment_run_id,q.deployment_stage,"
        "q.deployment_member_item_id,q.execution_target_json,q.execution_target_digest FROM qa_requirements q "
        "JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
        f"WHERE ({identity}) "
        f"AND NOT {settled_obligation_sql(conn, 'q')} "
        f"AND dr.status IN ({statuses}) "
        "AND (q.deployment_member_item_id IS NOT NULL OR EXISTS ("
        "SELECT 1 FROM deployment_run_items m WHERE m.run_id=q.deployment_run_id "
        f"AND m.item_id={placeholder})) "
        "ORDER BY q.id",
        (
            *identity_params,
            *sorted(ACTIVE_RUN_STATUSES),
            int(source["item_id"]),
        ),
    )
    copies: list[AdmittedCopy] = []
    for row in rows:
        if row["deployment_member_item_id"] is None:
            from yoke_core.domain.deployment_qa_shared_copy_reads import (
                member_owns_shared_copy,
            )

            if not member_owns_shared_copy(conn, row, int(source["item_id"])):
                continue
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
    placeholder = marker(conn)
    updated: list[int] = []
    for copy in copies:
        conn.execute(
            f"UPDATE qa_requirements SET {field} = {placeholder} "
            f"WHERE id = {placeholder}",
            (value, copy.requirement_id),
        )
        updated.append(copy.requirement_id)
    from yoke_core.domain.qa_plan_execution_roster_correction import (
        correct_live_rosters,
    )

    correct_live_rosters(conn, updated)
    return updated, ""


def _already_holds(conn: Any, copy_id: int, field: str, value: Any) -> bool:
    """True when the copy already carries ``value``: nothing to reach.

    An answered copy whose field is unchanged blocks nothing; only a copy the
    amendment would actually rewrite has to be reachable.
    """
    row = query_one(
        conn,
        f"SELECT {field} FROM qa_requirements WHERE id={marker(conn)}",
        (int(copy_id),),
    )
    return definition_value(field, row[field]) == definition_value(field, value)


__all__ = [
    "ADMITTED_COPY_IN_FLIGHT_CODE",
    "AdmittedCopy",
    "admitted_copies_in_flight",
    "reconcile_admitted_copies",
    "unreachable_copy_refusal",
]
