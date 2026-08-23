"""Handler registration for the organizations.* read family."""
from __future__ import annotations

from yoke_core.domain.handlers import organizations_get as _org
from yoke_core.domain.handlers import organizations_settings as _settings


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
    registry.register(
        "organizations.settings.catalog",
        _settings.handle_organization_settings_catalog,
        _settings.OrganizationSettingsCatalogRequest,
        _settings.OrganizationSettingsCatalogResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.organizations_settings",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"], guardrails=[],
        adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "organizations.settings.get",
        _settings.handle_organization_settings_get,
        _settings.OrganizationSettingsGetRequest,
        _settings.OrganizationSettingsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.organizations_settings",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"], guardrails=[],
        adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "organizations.settings.merge",
        _settings.handle_organization_settings_merge,
        _settings.OrganizationSettingsMergeRequest,
        _settings.OrganizationSettingsMergeResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.organizations_settings",
        target_kinds=["global"], side_effects=["organizations_update"],
        emitted_event_names=["YokeFunctionCalled"], guardrails=[],
        adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "organizations.domain.set",
        _settings.handle_organization_domain_set,
        _settings.OrganizationDomainSetRequest,
        _settings.OrganizationDomainSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.organizations_settings",
        target_kinds=["global"], side_effects=["organizations_update"],
        emitted_event_names=["OrganizationDomainChanged", "YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
