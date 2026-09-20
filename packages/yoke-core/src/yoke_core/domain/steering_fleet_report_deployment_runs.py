"""How each live deployment run is doing, for the seat that has to decide.

A run that stalls says nothing. Its stage stays "current", its obligations
stay unresolved, and no surface answers "has this been at this stage for
four hours, and is any of it red" — so the only remedy anyone reached for
was to cancel the run, which strands its members and discards re-authored
waivers.

The facts were already readable. ``unresolved_blocking_qa`` and
``blocking_obligation_total`` in
:mod:`deployment_run_completion_preconditions` are plain connection reads
with no execution lock between them and a caller, and they produce exactly
the sentences an operator needs; their only consumer was a driver-side
print behind the lock. This detector reads them from the report side, adds
the stage age and the red requirements with the members they belong to,
and renders one row per live run.

It decides nothing. There is no timeout and no auto-cancel here on
purpose: a run that has been at a stage for hours is *reported*, and a
person reads the row and chooses. The only rows marked as needing action
are the two the run cannot leave by itself — one holding a determinate
failing verdict, and one with nothing outstanding that is simply waiting
to be re-driven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.deployment_run_completion_preconditions import (
    blocking_obligation_total,
    redrive_recovery,
    unresolved_blocking_qa,
)
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker


@dataclass(frozen=True)
class RedRequirement:
    """One blocking requirement whose latest verdict is a determinate failure."""

    requirement_id: int
    verdict: str
    #: The run member this requirement was scoped to, empty for a run-wide one.
    member_ref: str = ""

    def describe(self) -> str:
        subject = self.member_ref or "run-wide"
        return f"{subject} #{self.requirement_id} {self.verdict}"


@dataclass(frozen=True)
class DeploymentRunProgress:
    """One live run's stage, age, and outstanding blocking QA."""

    run_id: str
    flow: str
    status: str
    stage: str
    #: Seconds since this stage's most recent receipt, or since the run
    #: started when the stage has produced none. ``None`` when neither is
    #: readable — reported as unknown rather than guessed at as zero.
    stage_seconds: Optional[int]
    outstanding: int
    total_blocking: int
    unresolved: tuple[str, ...]
    red: tuple[RedRequirement, ...]

    @property
    def needs_action(self) -> bool:
        """True when nothing the run is waiting for can arrive by itself."""
        return bool(self.red) or self.outstanding == 0

    def recovery(self) -> str:
        return redrive_recovery(self.run_id, unresolved=self.outstanding)


def _live_runs(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    p = marker(conn)
    terminal = sorted(TERMINAL_RUN_STATUSES)
    holes = ", ".join(p for _ in terminal)
    rows = conn.execute(
        f"""SELECT id, flow, status, COALESCE(current_stage, '') AS current_stage,
                   started_at, created_at
              FROM deployment_runs
             WHERE project_id = {p}
               AND status NOT IN ({holes})
             ORDER BY id""",
        (int(project_id), *terminal),
    ).fetchall()
    return [row_dict(row) for row in rows]


def _stage_entered_at(conn: Any, *, run_id: str, stage: str) -> str:
    """When this run most recently began the stage it is sitting at.

    The newest receipt for the stage is the moment it was last attempted.
    A stage that has produced no receipt has not started, so the caller
    falls back to the run's own clock rather than reporting no age.
    """
    if not stage or not _table_exists(conn, "deployment_stage_receipts"):
        return ""
    p = marker(conn)
    row = conn.execute(
        f"""SELECT created_at FROM deployment_stage_receipts
             WHERE run_id = {p} AND stage_name = {p}
             ORDER BY created_at DESC, id DESC LIMIT 1""",
        (run_id, stage),
    ).fetchone()
    return str(row[0] or "") if row is not None else ""


def _red_requirements(conn: Any, *, run_id: str) -> tuple[RedRequirement, ...]:
    """Blocking requirements of this run whose latest verdict is red.

    Latest is per requirement, matching what the stage gate grades: an
    earlier failure a later pass replaced is not a red requirement, and
    reporting it as one would send the operator after a case that is fine.
    The newest verdict is selected per row rather than joined, so the read
    runs unchanged on every backend the report composes against.
    """
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return ()
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT r.id,
                   (SELECT qr.verdict FROM qa_runs qr
                     WHERE qr.qa_requirement_id = r.id
                     ORDER BY qr.created_at DESC, qr.id DESC LIMIT 1) AS verdict,
                   p.slug, p.public_item_prefix, i.project_sequence
              FROM qa_requirements r
              LEFT JOIN items i ON i.id = r.deployment_member_item_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.deployment_run_id = {p}
               AND r.blocking_mode = 'blocking'
               AND r.waived_at IS NULL
               AND r.superseded_by_requirement_id IS NULL
             ORDER BY r.id""",
        (run_id,),
    ).fetchall()
    found = []
    for raw in rows:
        row = row_dict(raw)
        verdict = str(row["verdict"] or "")
        if verdict not in RED_VERDICTS:
            continue
        ref = ""
        if row.get("project_sequence") is not None:
            ref = format_item_ref(
                row["slug"], row["public_item_prefix"], row["project_sequence"]
            )
        found.append(
            RedRequirement(
                requirement_id=int(row["id"]),
                verdict=verdict,
                member_ref=ref,
            )
        )
    return tuple(found)


def run_progress(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[DeploymentRunProgress, ...]:
    """Every non-terminal run in the project, with what is holding it."""
    if not _table_exists(conn, "deployment_runs"):
        return ()
    rows = []
    for run in _live_runs(conn, project_id=project_id):
        run_id = str(run["id"])
        stage = str(run["current_stage"])
        unresolved = tuple(unresolved_blocking_qa(conn, run_id))
        entered = _stage_entered_at(conn, run_id=run_id, stage=stage) or str(
            run.get("started_at") or run.get("created_at") or ""
        )
        rows.append(
            DeploymentRunProgress(
                run_id=run_id,
                flow=str(run["flow"] or ""),
                status=str(run["status"] or ""),
                stage=stage or "unstarted",
                stage_seconds=age_seconds(entered, now),
                outstanding=len(unresolved),
                total_blocking=blocking_obligation_total(conn, run_id),
                unresolved=unresolved,
                red=_red_requirements(conn, run_id=run_id),
            )
        )
    return tuple(rows)


__all__ = [
    "DeploymentRunProgress",
    "RedRequirement",
    "run_progress",
]
