"""Derive one exact deployment run stage's approval verdict, server-side.

This is where the approval gate is decided, because this process is the
build that serves the database the decision rows live in. A caller running
a different revision — a release driver carrying the candidate, most often
— asks for the verdict rather than computing one, so a release that adds or
retires a column cannot crash its own approval gate.

Deciding is not approving. This creates or re-reads the decision request the
declared policy calls for and reports what the stage is still waiting on; a
person recording an answer goes through ``deployment_runs.approve``.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.deployment_approval_requests import (
    EVALUATE_STAGE_APPROVAL_FUNCTION as FUNCTION_ID,
)
from yoke_core.domain.handlers.deployment_common import error, run_id


def handle_deployment_stage_approval_evaluate(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, FUNCTION_ID)
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    stage = payload.get("stage")
    if not isinstance(stage, str) or not stage.strip():
        return error(
            "payload_invalid",
            f"{FUNCTION_ID} requires payload.stage naming the exact stage to "
            "evaluate; read it from `yoke deployment-runs stages RUN-ID`",
            jsonpath="$.payload.stage",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_approval_requests import (
        evaluate_deployment_stage_approval,
    )

    conn = connect()
    try:
        verdict = evaluate_deployment_stage_approval(
            conn,
            run_id=resolved_run_id,
            stage=stage.strip(),
            originator_actor_id=request.actor.actor_id,
            session_id=request.actor.session_id,
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except ValueError as exc:
        return error("invalid_state", str(exc))
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "stage": stage.strip(),
            "satisfied": bool(verdict.satisfied),
            "request_id": int(verdict.request_id),
            "request_status": str(verdict.request_status),
            "resolution_action": verdict.resolution_action,
            "reason": str(verdict.reason),
        },
        primary_success=True,
    )


__all__ = ["handle_deployment_stage_approval_evaluate"]
