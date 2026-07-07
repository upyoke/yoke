"""Best-effort telemetry for the external sign-in identity domain.

One shared emit surface for the identity-link, invite, web-session, and
sign-in modules so every event in the family carries the same envelope
shape. Emission is telemetry-only: the DB rows the domain functions write
remain the source of truth, and an emit failure never fails the caller
(the same stance :mod:`yoke_core.domain.coordination_leases` takes).

Never place raw tokens or id_token material in ``context`` — actor ids,
issuers, email addresses, and refusal-reason kinds only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


EVENT_EXTERNAL_IDENTITY_LINKED = "ExternalIdentityLinked"
EVENT_SIGN_IN_SUCCEEDED = "SignInSucceeded"
EVENT_SIGN_IN_REFUSED = "SignInRefused"
EVENT_ACTOR_INVITE_CREATED = "ActorInviteCreated"
EVENT_ACTOR_INVITE_ACCEPTED = "ActorInviteAccepted"
EVENT_ACTOR_INVITE_REVOKED = "ActorInviteRevoked"
EVENT_AUTO_JOIN_DOMAIN_CHANGED = "AutoJoinDomainChanged"

_EVENT_TYPES = {
    EVENT_EXTERNAL_IDENTITY_LINKED: "external_identity",
    EVENT_SIGN_IN_SUCCEEDED: "sign_in",
    EVENT_SIGN_IN_REFUSED: "sign_in",
    EVENT_ACTOR_INVITE_CREATED: "actor_invite",
    EVENT_ACTOR_INVITE_ACCEPTED: "actor_invite",
    EVENT_ACTOR_INVITE_REVOKED: "actor_invite",
    EVENT_AUTO_JOIN_DOMAIN_CHANGED: "org_settings",
}


def emit_identity_event(
    name: str,
    *,
    severity: str = "INFO",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one identity-domain event against the ambient events authority."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            name,
            event_kind="lifecycle",
            event_type=_EVENT_TYPES.get(name, "external_identity"),
            source_type="api",
            severity=severity,
            outcome="completed",
            context=dict(context or {}),
        )
    except Exception:
        # Best-effort telemetry; the identity rows remain the source of truth.
        pass


__all__ = [
    "EVENT_ACTOR_INVITE_ACCEPTED",
    "EVENT_ACTOR_INVITE_CREATED",
    "EVENT_ACTOR_INVITE_REVOKED",
    "EVENT_AUTO_JOIN_DOMAIN_CHANGED",
    "EVENT_EXTERNAL_IDENTITY_LINKED",
    "EVENT_SIGN_IN_REFUSED",
    "EVENT_SIGN_IN_SUCCEEDED",
    "emit_identity_event",
]
