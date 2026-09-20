"""Human rendering for a recorded deployment stage approval.

One approval is not always an approved stage: under an every-approver policy
the caller's decision is recorded and the stage keeps waiting. Reporting
"Approved" there would tell the operator the pipeline may move on when it may
not, so the two outcomes read differently and name what is still outstanding.

A cleared stage does not move the run either -- only the deployment runner
advances a run -- so the cleared outcome prints the commands that re-enter it
rather than leaving the reader to infer that the pipeline resumed by itself.
Those commands are rendered by the serving build and carried in the response,
because this adapter must keep importing on a client-only install.
"""

from __future__ import annotations

from typing import Any, Mapping, TextIO

APPROVE_COMMAND_DESCRIPTION = (
    "Record your approval on the run's current human-approval stage. The "
    "stage declares the same approval policy every Yoke gate declares: under "
    'mode "any" your approval settles it, under mode "all" it is recorded and '
    "the stage keeps waiting for the rest. Read stage_approved and "
    "approval_progress in the result — the stage cleared only when "
    "stage_approved is true, and DeploymentApprovalGranted is emitted only "
    "then. A cleared stage does not advance the run by itself: clearing it "
    "wakes the project's deploy-lock driver (its steering seat when nobody "
    "holds the lock) with the commands that re-enter the runner, which this "
    "command also prints."
)


def write_run_approval(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Print whether the stage cleared, or who it is still waiting on."""
    run_id = result.get("run_id")
    stage = result.get("approved_stage")
    if result.get("stage_approved", True):
        print(
            f"Approved {run_id}: {stage} -> {result.get('next_stage')}",
            file=stdout,
        )
        recipe = str(result.get("drive_recipe") or "")
        if recipe:
            print(
                "The run is still standing at that stage until the runner is "
                "re-entered on it:",
                file=stdout,
            )
            print(recipe, file=stdout)
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
