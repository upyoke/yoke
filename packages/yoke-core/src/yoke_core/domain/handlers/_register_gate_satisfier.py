"""Register the internal gate-satisfier ladder resolution surface.

``gate_satisfier.rung.resolve`` is engine glue: gates call it to turn
their site observations into a rung verdict and a durable stamp. It is
``adapter_status='internal'`` — never an agent CLI surface — so it needs
no CLI adapter row. Agents read the resulting stamps from item detail.
"""

from __future__ import annotations

from yoke_core.domain.handlers import gate_satisfier_rung as _rung

_MODULE = "yoke_core.domain.handlers.gate_satisfier_rung"


def register(registry) -> None:
    registry.register(
        "gate_satisfier.rung.resolve",
        _rung.handle_resolve,
        _rung.GateSatisfierResolveRequest,
        _rung.GateSatisfierResolveResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_gate_satisfactions_upsert"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "GateSatisfierRungStamped",
            "GateSatisfierRefused",
        ],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
