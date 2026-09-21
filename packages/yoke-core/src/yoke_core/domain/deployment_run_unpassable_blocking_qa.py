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
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_message_types import row_dict


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
            f"release_lineage {self.pin}."
        )


@dataclass(frozen=True)
class UnprovenPinQa:
    """A red requirement whose containment against the pin could not be read."""

    requirement_id: int
    member_ref: str
    merge_sha: str
    pin: str
    reason: str

    def note(self) -> str:
        subject = self.member_ref or "run-wide"
        pin = self.pin or "(none)"
        return (
            f"{subject} #{self.requirement_id} failed; whether recorded merge "
            f"{self.merge_sha} is in release_lineage {pin} is unproven "
            f"({self.reason}). Do not treat this run as unable to pass on "
            "that evidence."
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
    run = _run_pin(conn, run_id)
    if run is None:
        return PinQaDiagnosis()
    red = _red_members(conn, run_id)
    if not red:
        return PinQaDiagnosis()
    item_ids = tuple(row.item_id for row in red if row.item_id is not None)
    merges = recorded_merge_shas_for_items(conn, item_ids)
    if not any(merges.get(item_id) for item_id in item_ids):
        return PinQaDiagnosis()
    pin = run.pin
    walker = None
    if pin:
        walker = (containment_cls or CandidateContainment)(
            conn, run.project_id, candidate_lineage=pin,
        )
    unpassable: list[UnpassablePinQa] = []
    unproven: list[UnprovenPinQa] = []
    for row in red:
        if row.item_id is None:
            continue
        shas = merges.get(row.item_id, ())
        if not shas:
            continue
        newest = shas[0]
        if walker is None:
            unproven.append(
                UnprovenPinQa(
                    requirement_id=row.requirement_id,
                    member_ref=row.member_ref,
                    merge_sha=newest,
                    pin=pin,
                    reason="containment_operands_missing",
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
                )
            )
    return PinQaDiagnosis(unpassable=tuple(unpassable), unproven=tuple(unproven))


@dataclass(frozen=True)
class _RunPin:
    project_id: int
    pin: str


@dataclass(frozen=True)
class _RedMember:
    requirement_id: int
    item_id: Optional[int]
    member_ref: str


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run_pin(conn: Any, run_id: str) -> Optional[_RunPin]:
    p = _placeholder(conn)
    columns = "id, project_id"
    if _column_exists(conn, "deployment_runs", "release_lineage"):
        columns += ", COALESCE(release_lineage, '') AS release_lineage"
    row = conn.execute(
        f"SELECT {columns} FROM deployment_runs WHERE id = {p}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    record = row_dict(row)
    return _RunPin(
        project_id=int(record["project_id"]),
        pin=str(record.get("release_lineage") or "").strip(),
    )


def _red_members(conn: Any, run_id: str) -> tuple[_RedMember, ...]:
    if not _column_exists(conn, "qa_requirements", "deployment_member_item_id"):
        return ()
    p = _placeholder(conn)
    superseded = ""
    if _column_exists(conn, "qa_requirements", "superseded_by_requirement_id"):
        superseded = "AND r.superseded_by_requirement_id IS NULL"
    waived = ""
    if _column_exists(conn, "qa_requirements", "waived_at"):
        waived = "AND r.waived_at IS NULL"
    rows = conn.execute(
        f"""SELECT r.id,
                   r.deployment_member_item_id,
                   (SELECT qr.verdict FROM qa_runs qr
                     WHERE qr.qa_requirement_id = r.id
                     ORDER BY qr.created_at DESC, qr.id DESC LIMIT 1) AS verdict,
                   p.slug, p.public_item_prefix, i.project_sequence
              FROM qa_requirements r
              LEFT JOIN items i ON i.id = r.deployment_member_item_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.deployment_run_id = {p}
               AND r.blocking_mode = 'blocking'
               {waived}
               {superseded}
             ORDER BY r.id""",
        (run_id,),
    ).fetchall()
    found = []
    for raw in rows:
        record = row_dict(raw)
        if str(record["verdict"] or "") not in RED_VERDICTS:
            continue
        item_id = record.get("deployment_member_item_id")
        ref = ""
        if record.get("project_sequence") is not None:
            ref = format_item_ref(
                record["slug"], record["public_item_prefix"], record["project_sequence"]
            )
        found.append(
            _RedMember(
                requirement_id=int(record["id"]),
                item_id=int(item_id) if item_id is not None else None,
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
