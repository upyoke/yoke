"""Register idea/refine readiness function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import readiness as _readiness


def register(registry) -> None:
    registry.register(
        "readiness.check.run",
        _readiness.handle_check,
        _readiness.ReadinessCheckRequest,
        _readiness.ReadinessCheckResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.readiness",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "readiness.prd_validate.run",
        _readiness.handle_prd_validate,
        _readiness.ReadinessPrdValidateRequest,
        _readiness.ReadinessPrdValidateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.readiness",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "readiness.repair_stale_count",
        _readiness.handle_repair_stale_count,
        _readiness.ReadinessRepairRequest,
        _readiness.ReadinessRepairResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.readiness",
        target_kinds=["item"],
        side_effects=["items_spec_structured_write"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "IdeaReadinessAutofixApplied",
        ],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "readiness.repair_claim_coverage",
        _readiness.handle_repair_claim_coverage,
        _readiness.ReadinessRepairRequest,
        _readiness.ReadinessRepairResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.readiness",
        target_kinds=["item"],
        side_effects=["path_claim_amendments_insert"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "IdeaReadinessClaimCoverageRepairApplied",
        ],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )


__all__ = ["register"]
