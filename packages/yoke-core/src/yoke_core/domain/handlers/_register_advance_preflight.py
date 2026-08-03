"""Register the internal advance implementation-entry preflight gate evals.

These four ``advance.preflight.*`` functions are pure control-plane reads
the transport-aware advance preflight relays to so its refusal gates run
over an https control plane as well as a local Postgres connection. They
are ``adapter_status='internal'`` (preflight glue, never an agent CLI
surface), so they need no CLI adapter inventory row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import advance_preflight_gate_evals as _apg


def register(registry) -> None:
    registry.register(
        "advance.preflight.hard_blocks",
        _apg.handle_hard_blocks,
        _apg.HardBlocksEvalRequest,
        _apg.HardBlocksEvalResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.advance_preflight_gate_evals",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "advance.preflight.ac_presence",
        _apg.handle_ac_presence,
        _apg.AcPresenceEvalRequest,
        _apg.AcPresenceEvalResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.advance_preflight_gate_evals",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "advance.preflight.file_budget",
        _apg.handle_file_budget,
        _apg.FileBudgetEvalRequest,
        _apg.FileBudgetEvalResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.advance_preflight_gate_evals",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "advance.preflight.spec_coverage",
        _apg.handle_spec_coverage,
        _apg.SpecCoverageEvalRequest,
        _apg.SpecCoverageEvalResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.advance_preflight_gate_evals",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


__all__ = ["register"]
