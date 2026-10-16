"""Register one universe retention reader and stateless prune handler."""

from yoke_contracts.universe_retention import (
    PruneRequest,
    PruneResponse,
    RetentionReadRequest,
    RetentionResponse,
)
from yoke_core.domain.handlers.universe_retention import handle_get, handle_prune


def register(registry):
    for function_id, handler, request, response, writes in (
        (
            "universe.retention.get",
            handle_get,
            RetentionReadRequest,
            RetentionResponse,
            False,
        ),
        ("universe.prune.run", handle_prune, PruneRequest, PruneResponse, True),
    ):
        registry.register(
            function_id,
            handler,
            request,
            response,
            stability="stable",
            minimum_serving_version="next-release",
            owner_module="yoke_core.domain.handlers.universe_retention",
            target_kinds=["global"],
            claim_required_kind=None,
            ambient_session_required=False,
            adapter_status="live",
            side_effects=["retention_delete"] if writes else [],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["org_admin", "handler_managed_idempotency"],
        )
