"""When a run's blocking QA cannot pass against the pin it already chose.

A deployment run freezes ``release_lineage`` so what it ships is immutable.
A blocking post-deploy requirement is verified against that pin. A fail
whose remediation is a later merge cannot be satisfied by waiting, waiving
nothing, or re-driving the same run: re-drive re-executes against the same
lineage. This module only *says so*. It never terminalizes, supersedes, or
waives.

The hard part is proving the remediation exists and is outside the pin.
Elapsed time, a newer tip on the base branch, and later item activity are
not that proof. The evidence is a recorded merge identity for the failed
requirement's member, asked of the same containment walk a delivery gate
uses. ``not_contained`` is the only yes. ``contained`` is silence — the
fail may still be settleable against this pin. Anything else, including a
missing pin or an unreadable comparison, is named as unproven so a reader
is never invited to kill a run that could still succeed.

A run can carry more than its own project: a mixed-project release binds
other projects' sources, and a member belongs to whichever project owns it.
Its merge is asked of its own project's repository against the commit this
run pinned for that project, never of the run's project — commit ids from
two repositories are not comparable, and the provider answers such a
comparison with a 404 rather than a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.deployment_run_candidate_containment import (
    NOT_CONTAINED,
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_project_sources import run_source_sha
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_message_types import row_dict


OPERANDS_MISSING = "containment_operands_missing"
PROJECT_NOT_PINNED = "member_project_not_pinned"
PROJECT_NOT_PINNED_RECOVERY = (
    "This run pinned no source commit for the member's project, so there "
    "is nothing of that project here to compare its merge against; settle "
    "or waive the requirement on this run's own evidence."
)


@dataclass(frozen=True)
class UnpassablePinQa:
    """A red requirement whose recorded remediation is outside this pin."""

    requirement_id: int
    member_ref: str
    merge_sha: str
    pin: str

    def note(self) -> str:
        subject = self.member_ref or "run-wide"
        return (
            f"{subject} #{self.requirement_id} cannot pass against this pin: "
            f"recorded merge {self.merge_sha} is not contained in "
            f"the pinned source {self.pin}."
        )


@dataclass(frozen=True)
class UnprovenPinQa:
    """A red requirement whose containment against the pin could not be read."""

    requirement_id: int
    member_ref: str
    merge_sha: str
    pin: str
    reason: str
    recovery: str = ""

    def note(self) -> str:
        subject = self.member_ref or "run-wide"
        pin = self.pin or "(none)"
        recovery = f" {self.recovery}" if self.recovery else ""
        return (
            f"{subject} #{self.requirement_id} failed; whether recorded merge "
            f"{self.merge_sha} is in the pinned source {pin} is unproven "
            f"({self.reason}). Do not treat this run as unable to pass on "
            f"that evidence.{recovery}"
        )


@dataclass(frozen=True)
class PinQaDiagnosis:
    """Proven unpassable requirements, and the comparisons that could not answer."""

    unpassable: tuple[UnpassablePinQa, ...] = ()
    unproven: tuple[UnprovenPinQa, ...] = ()

    def notes(self) -> tuple[str, ...]:
        return tuple(item.note() for item in self.unpassable) + tuple(
            item.note() for item in self.unproven
        )

    def supersede_recovery(self, run_id: str) -> str:
        return (
            f"Re-drive cannot help: it re-executes against the same pin. "
            f"At independent item QA, use `yoke deployment-runs remove-item {run_id} "
            "ITEM --reason R` to let the run finish while the red member rides "
            "the next release (depth: `remove-item --help`); settlement automatically "
            "releases a member outside the frozen lineage. For shared gates: "
            f"Supersede {run_id} with a run pinned above the remediation. "
            "Terminalizing stays an operator action."
        )


def diagnose_unpassable_blocking_qa(
    conn: Any,
    *,
    run_id: str,
    containment_cls: Optional[type] = None,
) -> PinQaDiagnosis:
    """Return the pin-vs-remediation facts for ``run_id``'s red blocking QA."""
    if not (
        _table_exists(conn, "deployment_runs")
        and _table_exists(conn, "qa_requirements")
        and _table_exists(conn, "qa_runs")
    ):
        return PinQaDiagnosis()
    run_project_id = _run_project_id(conn, run_id)
    if run_project_id is None:
        return PinQaDiagnosis()
    red = _red_members(conn, run_id)
    if not red:
        return PinQaDiagnosis()
    item_ids = tuple(row.item_id for row in red if row.item_id is not None)
    merges = recorded_merge_shas_for_items(conn, item_ids)
    if not any(merges.get(item_id) for item_id in item_ids):
        return PinQaDiagnosis()
    walkers: dict[Optional[int], tuple[str, Any]] = {}
    unpassable: list[UnpassablePinQa] = []
    unproven: list[UnprovenPinQa] = []
    for row in red:
        if row.item_id is None:
            continue
        shas = merges.get(row.item_id, ())
        if not shas:
            continue
        newest = shas[0]
        project_id = row.project_id
        if project_id not in walkers:
            walkers[project_id] = _project_walker(
                conn, run_id, project_id, containment_cls
            )
        pin, walker = walkers[project_id]
        if walker is None:
            own = project_id == run_project_id
            unproven.append(
                UnprovenPinQa(
                    requirement_id=row.requirement_id,
                    member_ref=row.member_ref,
                    merge_sha=newest,
                    pin=pin,
                    reason=OPERANDS_MISSING if own else PROJECT_NOT_PINNED,
                    recovery="" if own else PROJECT_NOT_PINNED_RECOVERY,
                )
            )
            continue
        verdict = walker.contains(newest)
        if verdict.state == NOT_CONTAINED:
            unpassable.append(
                UnpassablePinQa(
                    requirement_id=row.requirement_id,
                    member_ref=row.member_ref,
                    merge_sha=newest,
                    pin=pin,
                )
            )
        elif verdict.state == UNDETERMINED:
            unproven.append(
                UnprovenPinQa(
                    requirement_id=row.requirement_id,
                    member_ref=row.member_ref,
                    merge_sha=newest,
                    pin=pin,
                    reason=verdict.reason or UNDETERMINED,
                    recovery=verdict.recovery,
                )
            )
    return PinQaDiagnosis(unpassable=tuple(unpassable), unproven=tuple(unproven))


@dataclass(frozen=True)
class _RedMember:
    requirement_id: int
    item_id: Optional[int]
    project_id: Optional[int]
    member_ref: str


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run_project_id(conn: Any, run_id: str) -> Optional[int]:
    row = conn.execute(
        f"SELECT project_id FROM deployment_runs WHERE id = {_placeholder(conn)}",
        (run_id,),
    ).fetchone()
    return None if row is None else int(row_dict(row)["project_id"])


def _project_walker(
    conn: Any,
    run_id: str,
    project_id: Optional[int],
    containment_cls: Optional[type],
) -> tuple[str, Any]:
    """The pin this run froze for one member project, and a walker over it.

    The run's own project answers from ``release_lineage``; a bound project
    from the commit the run recorded for it at start. No pin means no walker.
    """
    if project_id is None:
        return "", None
    pin = run_source_sha(conn, run_id, project_id)
    if not pin:
        return "", None
    walker = (containment_cls or CandidateContainment)(
        conn,
        project_id,
        candidate_lineage=pin,
    )
    return pin, walker


def _red_members(conn: Any, run_id: str) -> tuple[_RedMember, ...]:
    if not _column_exists(conn, "qa_requirements", "deployment_member_item_id"):
        return ()
    p = _placeholder(conn)
    from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
    from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql

    rows = conn.execute(
        f"""SELECT r.id,
                   r.deployment_member_item_id,
                   (SELECT qr.verdict FROM qa_runs qr
                     WHERE qr.id=({latest_execution_id_sql("r.id")})) AS verdict,
                   i.project_id, p.slug, p.public_item_prefix, i.project_sequence
              FROM qa_requirements r
              LEFT JOIN items i ON i.id = r.deployment_member_item_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.deployment_run_id = {p}
               AND r.blocking_mode = 'blocking'
               AND NOT {settled_obligation_sql(conn, "r")}
             ORDER BY r.id""",
        (run_id,),
    ).fetchall()
    found = []
    for raw in rows:
        record = row_dict(raw)
        if str(record["verdict"] or "") not in RED_VERDICTS:
            continue
        item_id = record.get("deployment_member_item_id")
        project_id = record.get("project_id")
        ref = ""
        if record.get("project_sequence") is not None:
            ref = format_item_ref(
                record["slug"], record["public_item_prefix"], record["project_sequence"]
            )
        found.append(
            _RedMember(
                requirement_id=int(record["id"]),
                item_id=int(item_id) if item_id is not None else None,
                project_id=int(project_id) if project_id is not None else None,
                member_ref=ref,
            )
        )
    return tuple(found)


__all__ = [
    "PinQaDiagnosis",
    "UnpassablePinQa",
    "UnprovenPinQa",
    "diagnose_unpassable_blocking_qa",
]
