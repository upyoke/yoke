"""Stage-boundary checks for the deploy pipeline: resume gate, unresolved QA.

Split out of ``deploy_pipeline`` so that module stays under the authored-file
line budget. Each check owns one boundary of ``run_pipeline`` and returns the
exit code the caller should use, or ``None`` when the pipeline may proceed.
Exit codes are passed in rather than duplicated here, since the caller
already owns their one authoritative definition.
"""

from __future__ import annotations

import sys
from typing import Any, Optional


def check_resume_qa_gate(
    *,
    run_id: str,
    start_stage: str,
    stage_failed_exit: int,
    awaiting_qa_exit: int,
) -> Optional[int]:
    """Refuse a resume that would skip a real scoped-QA gate.

    Returns an exit code when the resume must stop here, or ``None`` when
    it may proceed. A transport/authority failure evaluating the check is
    distinct from an empty result — conflating the two would let an
    unreachable serving plane read as "no scoped QA is outstanding". The
    serving side derives the stage list from the run's own stored flow;
    this caller supplies only the resume point.
    """
    from yoke_core.domain.deployment_qa_stage_resume import resume_qa_refusal_message

    try:
        qa_refusal = resume_qa_refusal_message(run_id=run_id, start_stage=start_stage)
    except RuntimeError as exc:
        print(
            f"Error: could not evaluate scoped QA resume gate: {exc}", file=sys.stderr
        )
        return stage_failed_exit
    if qa_refusal:
        print(
            "Error: resume cannot skip required scoped QA: " + qa_refusal,
            file=sys.stderr,
        )
        return awaiting_qa_exit
    return None


def report_missing_start_stage(
    flow_id: str, start_stage: str, stages: list[dict[str, Any]]
) -> None:
    """Print the diagnostic for a resume point absent from the flow."""
    print(
        f"Error: start stage '{start_stage}' not found in flow '{flow_id}'",
        file=sys.stderr,
    )
    print("Available stages:", file=sys.stderr)
    for stage in stages:
        print(f"  {stage['name']}", file=sys.stderr)


def check_unresolved_qa(
    run_id: str, *, usage_exit: int, awaiting_qa_exit: int
) -> Optional[int]:
    """Refuse completion while a blocking QA obligation is unresolved.

    Reporting here rather than letting the succeeded write refuse keeps the
    unresolved checks in the operator's output and skips the retry backoff,
    which exists for a transient write.
    """
    from yoke_core.domain import deploy_pipeline_control_plane as control_plane
    from yoke_core.domain.deployment_run_completion_preconditions import (
        awaiting_qa_report_lines,
    )

    try:
        unresolved_qa = control_plane.unresolved_qa(run_id)
    except control_plane.DeploymentControlPlaneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return usage_exit
    if unresolved_qa:
        for line in awaiting_qa_report_lines(run_id, unresolved_qa):
            print(line, file=sys.stderr)
        return awaiting_qa_exit
    return None


__all__ = [
    "check_resume_qa_gate",
    "check_unresolved_qa",
    "report_missing_start_stage",
]
