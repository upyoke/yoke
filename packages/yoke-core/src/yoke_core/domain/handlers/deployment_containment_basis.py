"""Containment-only read for a stale start attestation."""

from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.handlers.deployment_run_execution import _require_execution_lock

FUNCTION_ID = "deployment_runs.execution.containment_basis"


class Request(BaseModel):
    pass


class Response(BaseModel):
    candidate_containment_basis: dict


def handle(request):
    resolved = run_id(request, FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    if refusal := _require_execution_lock(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_contained_items import (
        CandidateContainmentRefusal,
        candidate_containment_basis,
    )
    from yoke_core.domain.schema_read_scope import composition_reads

    try:
        with composition_reads(), connect() as conn:
            basis = candidate_containment_basis(conn, resolved)
    except (CandidateContainmentRefusal, LookupError, ValueError) as exc:
        return error(
            "containment_basis_invalid",
            str(exc) + "; repair the named source, then re-drive the run",
        )
    return HandlerOutcome(
        result_payload={"candidate_containment_basis": basis}, primary_success=True
    )


def register(registry):
    registry.register(
        FUNCTION_ID,
        handle,
        Request,
        Response,
        stability="stable",
        owner_module=__name__,
        target_kinds=["workflow_run"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required"],
        adapter_status="live",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
