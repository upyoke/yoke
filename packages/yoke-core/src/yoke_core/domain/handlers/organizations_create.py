"""``organizations.create`` — found a new hosted organization.

Founding an organization provisions a new universe, so only Platform
answers this function: it intercepts the call on a machine's hosted
connection, applies the same founding checks as the site (signed-in
member, redeemed beta code, slug availability), and creates the org with
the caller as its founding admin. A universe engine never founds orgs —
a local or self-hosted universe carries exactly one — so every call that
reaches this handler refuses with the recovery named.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL

ORGANIZATION_CREATE_HOSTED_ONLY = "organization_create_hosted_only"


class OrganizationsCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    slug: Optional[str] = Field(default=None, max_length=40)


class OrganizationsCreateResponse(BaseModel):
    org: dict


def handle_organizations_create(request: FunctionCallRequest) -> HandlerOutcome:
    del request
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=ORGANIZATION_CREATE_HOSTED_ONLY,
            message=(
                "founding an organization is a hosted operation that Yoke "
                "Cloud answers; this universe engine never creates orgs (a "
                "local or self-hosted universe has exactly one). Run `yoke "
                "organizations create NAME` from a machine connected with "
                f"`yoke setup --connect {HOSTED_PLATFORM_URL}`, or found the "
                "org on the site"
            ),
        ),
    )


__all__ = [
    "ORGANIZATION_CREATE_HOSTED_ONLY",
    "OrganizationsCreateRequest",
    "OrganizationsCreateResponse",
    "handle_organizations_create",
]
