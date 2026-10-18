"""The fleet report's "waiting on manual wake" section.

Each row is one open manual-wake requirement of a waiting deployment-run
member (:mod:`deployment_qa_manual_wake`). The stage driver already woke its
owner to check the named evidence; the member's own line shows that wake's
state. A row stays until the case records a run, or is waived, superseded or
retracted, so a row that lingers is a waiver decision for the operator.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_manual_wake import ManualWakeRequirement
from yoke_core.domain.steering_fleet_report_deployment_runs import (
    DeploymentRunProgress,
)
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped

MANUAL_WAKE_HEADING = (
    "waiting on manual wake — each owner was woken to check its evidence; if "
    "this run cannot produce it, ask the operator to waive or remove the case"
)


def manual_wake_lines(runs: tuple[DeploymentRunProgress, ...]) -> list[str]:
    """Three lines per open manual-wake requirement across every live run."""
    entries = [entry for run in runs for entry in run.manual_wakes]
    lines: list[str] = []
    for entry in entries[:SECTION_LIMIT]:
        lines.extend(
            (
                f"  {entry.run_id}  {entry.item_ref}  requirement "
                f"#{entry.requirement_id} case {entry.case_key}  owner "
                f"{entry.owner()}",
                f"      evidence: {entry.wake_evidence}",
                f"      run: {entry.run_command()}",
            )
        )
    return capped(lines, len(entries))


def manual_wake_dict(entry: ManualWakeRequirement) -> dict[str, Any]:
    return {
        "run_id": entry.run_id,
        "stage": entry.stage,
        "item_ref": entry.item_ref,
        "requirement_id": entry.requirement_id,
        "case_key": entry.case_key,
        "wake_evidence": entry.wake_evidence,
        "owner_session_id": entry.owner_session_id,
        "owner_state": entry.owner_state,
        "run_command": entry.run_command(),
    }


__all__ = ["MANUAL_WAKE_HEADING", "manual_wake_dict", "manual_wake_lines"]
