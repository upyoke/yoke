"""Registered organization settings and identity-domain handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.identity_common import (
    caller_actor_id,
    resolve_org_ref,
)


class OrganizationSettingsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org: Optional[str] = None
    path: str


class OrganizationSettingsGetResponse(BaseModel):
    org_id: int
    path: str
    value: Any
    defaulted: bool


class OrganizationSettingsMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org: Optional[str] = None
    assignments: Dict[str, Any]


class OrganizationSettingsMergeResponse(BaseModel):
    org_id: int
    changed_paths: list[str]


class OrganizationDomainSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org: Optional[str] = None
    domain: Optional[str] = None


class OrganizationDomainSetResponse(BaseModel):
    org_id: int
    domain: Optional[str] = None


def _failure(code: str, message: str, path: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=path),
    )


def _parse(model, request: FunctionCallRequest):
    try:
        return model.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))


def handle_organization_settings_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    parsed = _parse(OrganizationSettingsGetRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.organization_settings import (
        OrganizationSettingsError,
        read_organization_setting,
    )

    conn = connect()
    try:
        org_id, error = resolve_org_ref(conn, parsed.org)
        if error is not None:
            return HandlerOutcome(primary_success=False, error=error)
        try:
            value, defaulted = read_organization_setting(
                conn,
                int(org_id),
                parsed.path,
            )
        except (OrganizationSettingsError, ValueError) as exc:
            return _failure("projection_invalid", str(exc), "$.payload.path")
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "org_id": int(org_id),
            "path": parsed.path,
            "value": value,
            "defaulted": defaulted,
        },
    )


def handle_organization_settings_merge(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    parsed = _parse(OrganizationSettingsMergeRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.organization_settings import (
        OrganizationSettingsError,
        merge_organization_settings,
    )

    conn = connect()
    try:
        org_id, error = resolve_org_ref(conn, parsed.org)
        if error is not None:
            return HandlerOutcome(primary_success=False, error=error)
        try:
            _, changed_paths = merge_organization_settings(
                conn,
                int(org_id),
                parsed.assignments,
            )
        except (OrganizationSettingsError, ValueError) as exc:
            return _failure("validation_error", str(exc), "$.payload.assignments")
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={"org_id": int(org_id), "changed_paths": changed_paths},
    )


def handle_organization_domain_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    parsed = _parse(OrganizationDomainSetRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.external_identities import (
        ExternalIdentityError,
        set_organization_domain,
    )

    conn = connect()
    try:
        org_id, error = resolve_org_ref(conn, parsed.org)
        if error is not None:
            return HandlerOutcome(primary_success=False, error=error)
        try:
            stored = set_organization_domain(
                conn,
                org_id=int(org_id),
                domain=parsed.domain,
                changed_by_actor_id=caller_actor_id(conn, request),
            )
        except ExternalIdentityError as exc:
            return _failure("validation_error", str(exc), "$.payload.domain")
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={"org_id": int(org_id), "domain": stored},
    )


__all__ = [
    "OrganizationDomainSetRequest",
    "OrganizationDomainSetResponse",
    "OrganizationSettingsGetRequest",
    "OrganizationSettingsGetResponse",
    "OrganizationSettingsMergeRequest",
    "OrganizationSettingsMergeResponse",
    "handle_organization_domain_set",
    "handle_organization_settings_get",
    "handle_organization_settings_merge",
]
