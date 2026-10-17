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
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_candidate_containment import (
    NOT_CONTAINED,
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_project_sources import run_source_sha
from yoke_core.domain.deployment_run_red_requirements import (
    RedRequirement,
    red_blocking_requirements,
)
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.schema_common import _table_exists
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
            "the next release (depth: `remove-item --help`); failed independent item QA and settlement automatically "
            "release a member definitely outside its project's frozen lineage; unknown containment holds. For shared gates: "
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
    if not _table_exists(conn, "deployment_runs"):
        return PinQaDiagnosis()
    run_project_id = _run_project_id(conn, run_id)
    if run_project_id is None:
        return PinQaDiagnosis()
    return diagnose_red_runs(
        conn,
        run_project_id=run_project_id,
        red_by_run=red_blocking_requirements(conn, (run_id,)),
        containment_cls=containment_cls,
    ).get(run_id, PinQaDiagnosis())


def diagnose_red_runs(
    conn: Any,
    *,
    run_project_id: int,
    red_by_run: Mapping[str, tuple[RedRequirement, ...]],
    containment_cls: Optional[type] = None,
) -> dict[str, PinQaDiagnosis]:
    """Diagnose already-read red requirements of one project's runs together.

    Every member's recorded merges are read once for the whole set; each
    run still compares them against its own pin.
    """
    item_ids = tuple(
        {red.item_id for reds in red_by_run.values() for red in reds if red.item_id}
    )
    merges = recorded_merge_shas_for_items(conn, item_ids) if item_ids else {}
    return {
        run_id: _diagnose_run(
            conn, run_id, run_project_id, reds, merges, containment_cls
        )
        for run_id, reds in red_by_run.items()
        if any(merges.get(red.item_id) for red in reds if red.item_id is not None)
    }


def _diagnose_run(
    conn: Any,
    run_id: str,
    run_project_id: int,
    red: tuple[RedRequirement, ...],
    merges: Mapping[int, tuple[str, ...]],
    containment_cls: Optional[type],
) -> PinQaDiagnosis:
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


__all__ = [
    "PinQaDiagnosis",
    "UnpassablePinQa",
    "UnprovenPinQa",
    "diagnose_red_runs",
    "diagnose_unpassable_blocking_qa",
]
