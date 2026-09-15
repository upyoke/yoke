"""Resume guard preventing later stages from bypassing scoped QA."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_stage_prerequisites import prior_stage_refusals


def prior_deployment_qa_refusals(
    conn: Any,
    *,
    run_id: str,
    stages: list[dict[str, Any]],
    start_stage: str,
) -> list[str]:
    """Prevent resume/from-stage from skipping an earlier scoped QA gate."""
    return prior_stage_refusals(
        conn, run_id=run_id, stages=stages, start_stage=start_stage
    )


def resume_qa_refusal_message(
    *, run_id: str, stages: list[dict[str, Any]], start_stage: str
) -> str:
    """Read and render the exact scoped-QA facts a resume would skip."""
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        refusals = prior_deployment_qa_refusals(
            conn, run_id=run_id, stages=stages, start_stage=start_stage
        )
    finally:
        conn.close()
    return "; ".join(refusals)


__all__ = ["prior_deployment_qa_refusals", "resume_qa_refusal_message"]
