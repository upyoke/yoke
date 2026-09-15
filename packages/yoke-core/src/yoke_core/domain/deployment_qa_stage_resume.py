"""Resume guard preventing later stages from bypassing scoped QA."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_stage_prerequisites import prior_stage_refusals

RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION = "deployment_runs.qa_stage.resume_refusals"


def prior_deployment_qa_refusals(
    conn: Any,
    *,
    run_id: str,
    stages: list[dict[str, Any]],
    start_stage: str,
) -> list[str]:
    """Prevent resume/from-stage from skipping an earlier scoped QA gate.

    Server-side implementation: the caller already holds a connection to
    the database that serves this control plane.
    """
    return prior_stage_refusals(
        conn, run_id=run_id, stages=stages, start_stage=start_stage
    )


def resume_qa_refusal_message(*, run_id: str, start_stage: str) -> str:
    """Read and render the exact scoped-QA facts a resume would skip.

    Reading these facts touches qa_requirements/qa_runs on the database
    that serves this control plane. The deploy driver may hold no local
    database authority at all — an ordinary project deploy works over
    HTTPS only — so this always dispatches to the serving build rather
    than connecting here. The stage list is derived server-side from the
    run's own stored flow, not accepted from this caller: a stage list is
    data a caller could omit or alter, and this check exists precisely to
    stop a resume from skipping a real gate.

    Raises ``RuntimeError`` when the serving plane could not evaluate the
    check at all — a transport/authority failure, distinct from an empty
    result. Conflating the two would read an unreachable serving plane as
    "no scoped QA is outstanding" and let a resume skip a real gate.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.control_plane_transport import serving_authority

    result = serving_authority(
        RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
        {"start_stage": start_stage},
        TargetRef(kind="workflow_run", workflow_run_id=run_id),
    )
    return str(result.get("message") or "")


__all__ = [
    "RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION",
    "prior_deployment_qa_refusals",
    "resume_qa_refusal_message",
]
