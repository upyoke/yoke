"""``organizations.get`` handler — read the org identity card.

Every universe carries at least one row in ``organizations`` (seeded by
``org_schema.seed_default_org`` during schema init and local-universe
birth). The default read returns the universe's identity card — the
lowest-id row, matching the single-card convention the local-universe
birth path uses — and an explicit ``slug`` payload addresses a specific
org on a multi-org instance.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class OrganizationsGetRequest(BaseModel):
    slug: Optional[str] = None


class OrganizationsGetResponse(BaseModel):
    slug: str
    name: str
    created_at: str


def handle_organizations_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect, query_one

    try:
        parsed = OrganizationsGetRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    conn = connect()
    try:
        if parsed.slug:
            placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = query_one(
                conn,
                "SELECT slug, name, created_at FROM organizations "
                f"WHERE slug = {placeholder}",
                (parsed.slug,),
            )
        else:
            row = query_one(
                conn,
                "SELECT slug, name, created_at FROM organizations "
                "ORDER BY id LIMIT 1",
            )
    finally:
        conn.close()
    if row is None:
        wanted = f"slug {parsed.slug!r}" if parsed.slug else "identity card"
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"no organization {wanted} exists on this universe",
                jsonpath="$.payload.slug",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "slug": str(row["slug"]),
            "name": str(row["name"]),
            "created_at": str(row["created_at"]),
        },
        primary_success=True,
    )


__all__ = [
    "OrganizationsGetRequest",
    "OrganizationsGetResponse",
    "handle_organizations_get",
]
