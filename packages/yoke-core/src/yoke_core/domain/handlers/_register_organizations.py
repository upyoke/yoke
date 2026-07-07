"""Handler registration for the organizations.* read family."""
from __future__ import annotations

from yoke_core.domain.handlers import organizations_get as _org


def register(registry) -> None:
    """Register the organizations read handler via the given registry module."""
    registry.register(
        "organizations.get", _org.handle_organizations_get,
        _org.OrganizationsGetRequest, _org.OrganizationsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.organizations_get",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
