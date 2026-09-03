"""Human rendering for a recorded deployment stage approval.

One approval is not always an approved stage: under an every-approver policy
the caller's decision is recorded and the stage keeps waiting. Reporting
"Approved" there would tell the operator the pipeline may move on when it may
not, so the two outcomes read differently and name what is still outstanding.
"""

from __future__ import annotations

from typing import Any, Mapping, TextIO


def write_run_approval(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Print whether the stage cleared, or who it is still waiting on."""
    run_id = result.get("run_id")
    stage = result.get("approved_stage")
    if result.get("stage_approved", True):
        print(
            f"Approved {run_id}: {stage} -> {result.get('next_stage')}",
            file=stdout,
        )
        return
    progress = result.get("approval_progress") or {}
    waiting = ", ".join(progress.get("outstanding") or []) or "another approver"
    print(
        f"Recorded your approval on {run_id} stage {stage!r}: "
        f"{progress.get('satisfied', 0)} of {progress.get('required', 0)} "
        f"decisions recorded, still waiting on {waiting}.",
        file=stdout,
    )


__all__ = ["write_run_approval"]
