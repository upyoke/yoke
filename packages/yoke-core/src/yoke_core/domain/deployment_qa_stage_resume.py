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

    Reading these facts touches qa_requirements/qa_runs through the
    registered function-call dispatcher, the same connection-keyed path
    ``deploy_pipeline_control_plane`` uses for every other execution-owned
    read: an admin-bootstrapped driver reads them locally, an ordinary
    HTTPS-connected driver relays to whatever build is actively serving
    that connection. The stage list is derived server-side from the run's
    own stored flow, not accepted from this caller: a stage list is data a
    caller could omit or alter, and this check exists precisely to stop a
    resume from skipping a real gate.

    Raises ``RuntimeError`` when the check could not be evaluated at all —
    a transport/authority failure, distinct from an empty result.
    Conflating the two would read an unreachable serving plane as "no
    scoped QA is outstanding" and let a resume skip a real gate.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    response = call_dispatcher(
        function_id=RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"start_stage": start_stage},
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        raise RuntimeError(
            f"{RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION} failed: {message}"
        )
    result = dict(response.result or {})
    return str(result.get("message") or "")


__all__ = [
    "RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION",
    "prior_deployment_qa_refusals",
    "resume_qa_refusal_message",
]
