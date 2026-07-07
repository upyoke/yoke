"""``identity.link.set`` and ``identity.autojoin.set`` handlers.

``identity.link.set`` has two shapes, both binding sign-in admission to
an EXISTING actor:

* ``issuer`` + ``subject`` (optional ``email``) — write the external
  identity link directly; the next sign-in with that identity resolves
  on the first ladder rung.
* ``email`` alone — write a pending pre-link invite carrying the target
  actor, so the next verified sign-in with that email binds its identity
  to that actor instead of creating a new one.

``identity.autojoin.set`` sets or clears ``organizations.auto_join_domain``.
Both are org-admin-gated at dispatch (``identity.`` prefix -> ORG scope).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.handlers.identity_common import (
    caller_actor_id,
    payload_error,
    resolve_actor_ref,
    resolve_org_ref,
)


class LinkSetRequest(BaseModel):
    actor: str
    issuer: Optional[str] = None
    subject: Optional[str] = None
    email: Optional[str] = None
    org: Optional[str] = None


class LinkSetResponse(BaseModel):
    actor_id: int
    link_kind: str  # "external_identity" | "email_pre_link"
    link_id: Optional[int] = None
    invite_id: Optional[int] = None


class AutojoinSetRequest(BaseModel):
    domain: Optional[str] = None
    org: Optional[str] = None


class AutojoinSetResponse(BaseModel):
    org_id: int
    domain: Optional[str] = None


def handle_identity_link_set(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.actor_invites import InviteError, create_invite
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.external_identities import (
        ExternalIdentityConflict,
        ExternalIdentityError,
        link_external_identity,
    )

    try:
        parsed = LinkSetRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(primary_success=False, error=payload_error(str(exc)))
    identity_shape = bool(parsed.issuer or parsed.subject)
    if identity_shape and not (parsed.issuer and parsed.subject):
        return HandlerOutcome(
            primary_success=False,
            error=payload_error(
                "issuer and subject must be supplied together",
            ),
        )
    if not identity_shape and not parsed.email:
        return HandlerOutcome(
            primary_success=False,
            error=payload_error(
                "supply issuer+subject (direct identity link) or email "
                "(pre-link a future sign-in to this actor)",
            ),
        )
    conn = connect()
    try:
        actor_id, actor_error = resolve_actor_ref(
            conn, parsed.actor, "$.payload.actor",
        )
        if actor_error is not None:
            return HandlerOutcome(primary_success=False, error=actor_error)
        if identity_shape:
            try:
                link_id = link_external_identity(
                    conn,
                    actor_id=actor_id,
                    issuer=parsed.issuer,
                    subject=parsed.subject,
                    email=parsed.email,
                    created_by_actor_id=caller_actor_id(conn, request),
                )
            except (ExternalIdentityConflict, ExternalIdentityError) as exc:
                return HandlerOutcome(
                    primary_success=False,
                    error=payload_error(str(exc), "$.payload.issuer"),
                )
            result = {
                "actor_id": actor_id,
                "link_kind": "external_identity",
                "link_id": link_id,
                "invite_id": None,
            }
        else:
            org_id, org_error = resolve_org_ref(conn, parsed.org)
            if org_error is not None:
                return HandlerOutcome(primary_success=False, error=org_error)
            try:
                invite = create_invite(
                    conn,
                    email=parsed.email,
                    org_id=org_id,
                    invited_by_actor_id=caller_actor_id(conn, request),
                    actor_id=actor_id,
                )
            except InviteError as exc:
                return HandlerOutcome(
                    primary_success=False,
                    error=payload_error(str(exc), "$.payload.email"),
                )
            result = {
                "actor_id": actor_id,
                "link_kind": "email_pre_link",
                "link_id": None,
                "invite_id": invite.invite_id,
            }
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_identity_autojoin_set(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.external_identities import (
        ExternalIdentityError,
        set_auto_join_domain,
    )

    try:
        parsed = AutojoinSetRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(primary_success=False, error=payload_error(str(exc)))
    conn = connect()
    try:
        org_id, org_error = resolve_org_ref(conn, parsed.org)
        if org_error is not None:
            return HandlerOutcome(primary_success=False, error=org_error)
        try:
            stored = set_auto_join_domain(
                conn,
                org_id=org_id,
                domain=parsed.domain,
                changed_by_actor_id=caller_actor_id(conn, request),
            )
        except ExternalIdentityError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=payload_error(str(exc), "$.payload.domain"),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"org_id": org_id, "domain": stored},
        primary_success=True,
    )


__all__ = [
    "AutojoinSetRequest",
    "AutojoinSetResponse",
    "LinkSetRequest",
    "LinkSetResponse",
    "handle_identity_autojoin_set",
    "handle_identity_link_set",
]
