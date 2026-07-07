"""Shared resolution helpers for the ``identity.*`` handler family.

Every identity handler is org-admin-gated at dispatch (the ``identity.``
prefix classifies ORG + ``org.admin`` in ``function_authz_scope``); these
helpers only translate payload references into row ids.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError

from yoke_core.domain import db_backend
from yoke_core.domain.actors import (
    SYSTEM_COMPONENT_YOKE_CORE,
    resolve_actor_by_label,
    seed_system_actor,
    validate_actor_id,
)
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.org_schema import org_id_by_slug


def payload_error(message: str, jsonpath: str = "$.payload") -> FunctionError:
    return FunctionError(code="payload_invalid", message=message, jsonpath=jsonpath)


def not_found_error(message: str, jsonpath: str = "$.payload") -> FunctionError:
    return FunctionError(code="not_found", message=message, jsonpath=jsonpath)


def caller_actor_id(conn: Any, request: FunctionCallRequest) -> int:
    """Resolve the calling actor id for attribution columns.

    The dispatcher fills ``request.actor.actor_id`` from the verified
    token/session server-side. Local source-dev dispatch may carry no
    numeric actor; attribution then falls back to the canonical
    ``yoke-core`` system actor (seeded idempotently).
    """
    raw = str(request.actor.actor_id or "").strip()
    if raw.isdigit():
        return int(raw)
    return seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)


def resolve_org_ref(
    conn: Any, org_ref: Optional[str],
) -> Tuple[Optional[int], Optional[FunctionError]]:
    """Resolve an optional org slug/id payload ref; default the identity-card org."""
    cleaned = str(org_ref or "").strip()
    if not cleaned:
        return default_org_id(conn), None
    if cleaned.isdigit():
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT id FROM organizations WHERE id = {p}", (int(cleaned),),
        ).fetchone()
        if row is None:
            return None, not_found_error(
                f"no organization with id {cleaned}", "$.payload.org",
            )
        return int(row[0]), None
    org_id = org_id_by_slug(conn, cleaned)
    if org_id is None:
        return None, not_found_error(
            f"no organization with slug {cleaned!r}", "$.payload.org",
        )
    return org_id, None


def resolve_actor_ref(
    conn: Any, actor_ref: str, jsonpath: str,
) -> Tuple[Optional[int], Optional[FunctionError]]:
    """Resolve an actor payload ref: a numeric id or a display label."""
    cleaned = str(actor_ref or "").strip()
    if not cleaned:
        return None, payload_error("actor reference must be non-empty", jsonpath)
    if cleaned.isdigit():
        actor_id = int(cleaned)
        if not validate_actor_id(conn, actor_id):
            return None, not_found_error(f"no actor with id {actor_id}", jsonpath)
        return actor_id, None
    actor_id = resolve_actor_by_label(conn, cleaned)
    if actor_id is None:
        return None, not_found_error(
            f"no actor labelled {cleaned!r}", jsonpath,
        )
    return actor_id, None


__all__ = [
    "caller_actor_id",
    "not_found_error",
    "payload_error",
    "resolve_actor_ref",
    "resolve_org_ref",
]
