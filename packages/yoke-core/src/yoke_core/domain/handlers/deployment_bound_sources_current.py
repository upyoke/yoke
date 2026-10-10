"""Whether a run's frozen bound sources still match their branches.

The deploy driver asks immediately before dispatching a stage that consumes
bound sources. The answer comes from the control plane because it is the
one place that can always read a bound project's branch head: through the
project's checkout where the serving machine has one, otherwise through
the repository binding the project already authorized.
"""

from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.deployment_run_stale_bound_sources import (
    BOUND_SOURCES_CURRENT_FUNCTION_ID as FUNCTION_ID,
)
from yoke_core.domain.handlers.deployment_common import run_id
from yoke_core.domain.handlers.deployment_run_execution import require_run_driver


class Request(BaseModel):
    pass


class Response(BaseModel):
    stale: list[dict[str, str]] = []
    unverified: str = ""


def handle(request):
    resolved = run_id(request, FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    if refusal := require_run_driver(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_stale_bound_sources import (
        check_bound_sources_current,
    )

    with connect() as conn:
        stale, unverified = check_bound_sources_current(conn, resolved)
    return HandlerOutcome(
        result_payload={"stale": stale, "unverified": unverified},
        primary_success=True,
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
        guardrails=["run_driver_required"],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
