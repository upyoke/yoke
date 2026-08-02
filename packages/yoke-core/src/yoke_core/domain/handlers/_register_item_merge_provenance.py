"""Register the operator repair for a terminal item's unset merge timestamp.

``adapter_status='wrapped'`` because this is the named human escape hatch
the terminal-immutability contract points at, so it ships a CLI adapter.
It is claim-free by necessity: a terminal item cannot be claimed, which is
the whole reason the ordinary scalar-write path cannot reach it. The
operator reason and the WARN ``OperatorMergedAtCorrection`` event carry the
accountability a claim would otherwise carry.
"""

from __future__ import annotations

from yoke_core.domain.handlers import item_merge_provenance as _writes

_MODULE = "yoke_core.domain.handlers.item_merge_provenance"


def register(registry) -> None:
    registry.register(
        "items.merge_provenance.operator_correct",
        _writes.handle_operator_correct_merged_at,
        _writes.OperatorCorrectMergedAtRequest,
        _writes.OperatorCorrectMergedAtResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_merged_at_write"],
        emitted_event_names=["YokeFunctionCalled", "OperatorMergedAtCorrection"],
        guardrails=[
            "human_only_no_hook_context",
            "terminal_item_required",
            "unset_merged_at_required",
            "operator_reason_required",
        ],
        adapter_status="wrapped",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
