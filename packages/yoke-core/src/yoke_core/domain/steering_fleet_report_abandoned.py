"""Find the launches whose worker was delivered its mandate and never started.

These are the rows nothing else on the report can show. Every other detector
reads a state that is visibly wrong — unclaimed work, a silent holder, an
unbound launch. An abandoned launch reads staffed: the item is claimed by
nobody, the launch is closed, and the seat that sent the worker has no reason
to look again unless the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.session_launch_abandonment import ABANDONED_RESULT_CODE
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker
from yoke_core.domain.steering_fleet_report_evidence import (
    evidence_int,
    evidence_text,
)


#: How long a corrected launch stays on the report. Long enough that a seat
#: reading its next report still sees a worker that died an hour ago, short
#: enough that yesterday's corrections are history rather than a standing list.
ABANDONED_LAUNCH_WINDOW_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class AbandonedLaunch:
    """One launch whose worker never started, and what its native last said."""

    launch_id: str
    surface: str
    machine_id: str
    session_id: str
    closed_seconds: int
    closure_reason: str = ""
    native_stderr_tail: str = ""
    exit_code: int | None = None
    native_diagnostic_ref: str = ""


def abandoned_launches(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[AbandonedLaunch, ...]:
    """Launches whose worker was delivered its mandate and never started it.

    Each row is work the seat believes is staffed and is not: the launch was
    corrected after delivery, so nothing else on the report says the item is
    unstarted. The native's own last words travel on the row because the
    capture behind them is readable only on the machine that produced it.
    """
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT launch_id, selected_surface, requested_surface,
                   assigned_machine_id, requested_machine_id,
                   registered_session_id, native_session_id,
                   completed_at, result_evidence
              FROM session_launches
             WHERE project_id = {p}
               AND result_code = {p}
             ORDER BY completed_at DESC, launch_id ASC""",
        (int(project_id), ABANDONED_RESULT_CODE),
    ).fetchall()
    abandoned = []
    for row in rows:
        record = dict(row)
        age = age_seconds(str(record.get("completed_at") or ""), now)
        if age is None or age >= ABANDONED_LAUNCH_WINDOW_SECONDS:
            continue
        evidence = record.get("result_evidence")
        abandoned.append(
            AbandonedLaunch(
                launch_id=str(record["launch_id"]),
                surface=str(
                    record.get("selected_surface")
                    or record.get("requested_surface")
                    or "unknown"
                ),
                machine_id=str(
                    record.get("assigned_machine_id")
                    or record.get("requested_machine_id")
                    or "unassigned"
                ),
                session_id=str(
                    record.get("registered_session_id")
                    or record.get("native_session_id")
                    or ""
                ),
                closed_seconds=age,
                closure_reason=evidence_text(evidence, "closure_reason"),
                native_stderr_tail=evidence_text(evidence, "native_stderr_tail"),
                exit_code=evidence_int(evidence, "exit_code"),
                native_diagnostic_ref=evidence_text(evidence, "native_diagnostic_ref"),
            )
        )
    return tuple(abandoned)


__all__ = [
    "ABANDONED_LAUNCH_WINDOW_SECONDS",
    "AbandonedLaunch",
    "abandoned_launches",
]
