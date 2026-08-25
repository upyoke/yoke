"""Leaf registration hook for strategy review and Blitz execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.handlers import strategy_doc_session_claims as doc_claims
from yoke_core.domain.handlers import strategy_doc_surfaces as handlers
from yoke_core.domain.handlers import strategy_doc_surface_reads as reads
from yoke_core.domain.handlers.strategy_doc_surface_models import (
    EmptyRequest,
    StrategyDocClaimAcquireRequest,
    StrategyDocClaimListRequest,
    StrategyDocClaimListResponse,
    StrategyDocClaimReleaseRequest,
    StrategyDocClaimResponse,
    StrategyCoordinationAppendRequest,
    StrategyCoordinationAppendResponse,
    StrategyExecutionClaimBreakGlassRequest,
    StrategyExecutionClaimReleaseRequest,
    StrategyExecutionLinkRequest,
    StrategyExecutionResponse,
    StrategyParentSetRequest,
    StrategyParentSetResponse,
    StrategyRevisionDiffRequest,
    StrategyRevisionDiffResponse,
    StrategyRevisionRestoreRequest,
    StrategyRevisionRestoreResponse,
    StrategySurfaceGetRequest,
    StrategySurfaceGetResponse,
    StrategySurfaceListResponse,
)
from yoke_core.domain.strategy_execution_events import (
    COORDINATION_APPENDED_EVENT,
)


def _registration(
    function_id: str,
    handler: Any,
    request_model: Any,
    response_model: Any,
    *,
    target_kind: str,
    side_effects: list[str],
    events: list[str] | None = None,
    guardrails: list[str] | None = None,
    claim_required_kind: str | None = None,
) -> dict[str, Any]:
    return {
        "function_id": function_id,
        "handler": handler,
        "request_model": request_model,
        "response_model": response_model,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_doc_surfaces",
        "target_kinds": [target_kind],
        "side_effects": side_effects,
        "emitted_event_names": events or [],
        "guardrails": guardrails or [],
        "adapter_status": "live",
        "claim_required_kind": claim_required_kind,
    }


REGISTRATIONS = [
    _registration("strategy.surface.list", reads.handle_surface_list, EmptyRequest,
                  StrategySurfaceListResponse, target_kind="global", side_effects=[]),
    _registration("strategy.surface.get", reads.handle_surface_get,
                  StrategySurfaceGetRequest, StrategySurfaceGetResponse,
                  target_kind="global", side_effects=[]),
    _registration("strategy.revision.diff", reads.handle_revision_diff,
                  StrategyRevisionDiffRequest, StrategyRevisionDiffResponse,
                  target_kind="global", side_effects=[]),
    _registration("strategy.revision.restore", reads.handle_revision_restore,
                  StrategyRevisionRestoreRequest, StrategyRevisionRestoreResponse,
                  target_kind="global", side_effects=["db_write", "event_emit"],
                  events=[handlers.REVISION_RESTORED_EVENT]),
    _registration("strategy.parent.set", reads.handle_parent_set,
                  StrategyParentSetRequest, StrategyParentSetResponse,
                  target_kind="global", side_effects=["db_write"]),
    _registration("strategy.coordination.append", reads.handle_coordination_append,
                  StrategyCoordinationAppendRequest,
                  StrategyCoordinationAppendResponse,
                  target_kind="global", side_effects=["db_write", "event_emit"],
                  events=[COORDINATION_APPENDED_EVENT]),
    _registration("strategy.execution.get", handlers.handle_execution_get,
                  EmptyRequest, StrategyExecutionResponse,
                  target_kind="item", side_effects=[]),
    _registration("strategy.execution.link", handlers.handle_execution_link,
                  StrategyExecutionLinkRequest, StrategyExecutionResponse,
                  target_kind="item", side_effects=["db_write"]),
    _registration("strategy.claim.acquire", handlers.handle_claim_acquire,
                  EmptyRequest, StrategyExecutionResponse, target_kind="item",
                  side_effects=["db_write", "event_emit"],
                  events=[handlers.CLAIM_ACQUIRED_EVENT]),
    _registration("strategy.claim.release", handlers.handle_claim_release,
                  StrategyExecutionClaimReleaseRequest, StrategyExecutionResponse,
                  target_kind="item", side_effects=["db_write", "event_emit"],
                  events=[handlers.CLAIM_RELEASED_EVENT]),
    _registration("strategy.doc_claim.acquire", doc_claims.handle_doc_claim_acquire,
                  StrategyDocClaimAcquireRequest, StrategyDocClaimResponse,
                  target_kind="global", side_effects=["db_write", "event_emit"],
                  events=[handlers.CLAIM_ACQUIRED_EVENT]),
    _registration("strategy.doc_claim.release", doc_claims.handle_doc_claim_release,
                  StrategyDocClaimReleaseRequest, StrategyDocClaimResponse,
                  target_kind="global", side_effects=["db_write", "event_emit"],
                  events=[handlers.CLAIM_RELEASED_EVENT]),
    _registration("strategy.doc_claim.list", doc_claims.handle_doc_claim_list,
                  StrategyDocClaimListRequest, StrategyDocClaimListResponse,
                  target_kind="global", side_effects=[]),
    _registration(
        "strategy.claim.break_glass_release",
        handlers.handle_claim_break_glass_release,
        StrategyExecutionClaimBreakGlassRequest,
        StrategyExecutionResponse,
        target_kind="item",
        side_effects=["db_write", "event_emit"],
        events=[handlers.CLAIM_BREAK_GLASS_EVENT],
        guardrails=["operator_override_required"],
        claim_required_kind="operator_override",
    ),
]


def register(registry) -> None:
    for entry in REGISTRATIONS:
        registry.register(**entry)


__all__ = ["REGISTRATIONS", "register"]
