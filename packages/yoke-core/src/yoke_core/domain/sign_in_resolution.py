"""Sign-in resolution ladder: verified id_token claims -> actor.

One entry point, :func:`resolve_sign_in`, takes the claims of an ALREADY
VERIFIED id_token (signature, issuer, audience, expiry, nonce all checked
upstream) and answers "which actor is signing in?" by walking four rungs:

1. **Linked identity.** ``(issuer, subject)`` already bound in
   ``actor_external_identities`` -> that actor.
2. **Pending invite.** A pending ``actor_invites`` row matches the
   verified email (case-insensitive) -> accept it. An invite carrying a
   target ``actor_id`` (email pre-link) binds the identity to that
   existing actor; otherwise a new human actor is created (label from
   the email local part, then the ``name`` claim). The invite's
   ``role_id``, when set, grants that org role.
3. **Auto-join domain.** The email's domain equals the org's
   ``auto_join_domain`` -> create actor + link, no role grant.
4. **Refusal** with an operator-facing reason kind.

Email trust is strict by default: rungs 2-3 only consider the email when
the id_token marks ``email_verified`` true. A provider that omits the
claim entirely is trusted only when the operator opted in
(``allow_unverified_email=True``); an explicit ``email_verified: false``
is never trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actor_invites import (
    Invite,
    mark_invite_accepted,
    pending_invite_for_email,
)
from yoke_core.domain.actor_permissions import grant_actor_org_role
from yoke_core.domain.actors import (
    resolve_actor_by_label,
    seed_human_actor,
    set_actor_label,
)
from yoke_core.domain.external_identities import (
    auto_join_domain,
    default_org_id,
    link_external_identity,
    resolve_external_identity,
)
from yoke_core.domain.external_identity_events import (
    EVENT_SIGN_IN_REFUSED,
    EVENT_SIGN_IN_SUCCEEDED,
    emit_identity_event,
)


OUTCOME_LINKED_IDENTITY = "linked_identity"
OUTCOME_INVITE_ACCEPTED = "invite_accepted"
OUTCOME_AUTO_JOINED = "auto_joined"
OUTCOME_REFUSED = "refused"

REFUSAL_MISSING_REQUIRED_CLAIMS = "missing_required_claims"
REFUSAL_MISSING_EMAIL_CLAIM = "missing_email_claim"
REFUSAL_EMAIL_UNVERIFIED = "email_unverified"
REFUSAL_NO_ADMISSION_MATCH = "no_invite_or_auto_join_match"


@dataclass(frozen=True)
class SignInResolution:
    """Outcome of one sign-in attempt.

    ``refusal_reason`` is a stable machine kind (one of the ``REFUSAL_*``
    constants) when ``outcome == "refused"``; ``detail`` is the
    operator-facing sentence for logs and error pages.
    """

    actor_id: Optional[int]
    outcome: str
    refusal_reason: Optional[str]
    detail: str

    @property
    def succeeded(self) -> bool:
        return self.outcome != OUTCOME_REFUSED


def _claim_is_true(value: Any) -> bool:
    """Whether an id_token boolean claim asserts truth.

    OIDC providers and SAML->OIDC bridges serialize ``email_verified``
    inconsistently: a native JSON ``true``/``false``, or the STRINGS
    ``"true"``/``"false"``. A bare ``bool(value)`` would trust the string
    ``"false"`` (non-empty -> truthy), silently defeating the strict
    email-trust invariant. Trust only a real ``True`` or an explicit
    true-string; every other shape (``False``, ``"false"``, ``"0"``,
    numbers, ``None``, unknown types) is untrusted.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def _email_domain(email: str) -> Optional[str]:
    _, _, domain = email.partition("@")
    return domain.strip().lower() or None


def _label_base(email: str, name_claim: Optional[str]) -> str:
    local = email.partition("@")[0].strip()
    if local:
        return local
    name = str(name_claim or "").strip()
    return name or "member"


def _create_labelled_actor(conn: Any, *, email: str, name_claim: Optional[str]) -> int:
    """Create a human actor labelled from the email local part.

    Labels are unique per surface, so collisions get a numeric suffix;
    the actor id itself is the durable identity, the label is display.
    """
    actor_id = seed_human_actor(conn)
    base = _label_base(email, name_claim)
    label = base
    suffix = 2
    while resolve_actor_by_label(conn, label) is not None:
        label = f"{base}-{suffix}"
        suffix += 1
        if suffix > 50:
            label = f"{base}-{actor_id}"
            break
    set_actor_label(conn, actor_id, label)
    return actor_id


def _grant_invite_role(conn: Any, invite: Invite, actor_id: int) -> None:
    if invite.role_id is None:
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT name FROM roles WHERE id = {p}",
        (invite.role_id,),
    ).fetchone()
    if row is None:
        return
    grant_actor_org_role(
        conn,
        actor_id=actor_id,
        org_id=invite.org_id,
        role_name=str(row[0]),
        granted_by_actor_id=invite.invited_by_actor_id,
    )


def _succeed(issuer: str, actor_id: int, outcome: str, detail: str) -> SignInResolution:
    emit_identity_event(
        EVENT_SIGN_IN_SUCCEEDED,
        context={"actor_id": actor_id, "issuer": issuer, "outcome": outcome},
    )
    return SignInResolution(
        actor_id=actor_id, outcome=outcome, refusal_reason=None, detail=detail,
    )


def _refuse(issuer: Optional[str], reason: str, detail: str) -> SignInResolution:
    emit_identity_event(
        EVENT_SIGN_IN_REFUSED,
        severity="WARN",
        context={"issuer": issuer, "refusal_reason": reason},
    )
    return SignInResolution(
        actor_id=None, outcome=OUTCOME_REFUSED, refusal_reason=reason, detail=detail,
    )


def resolve_sign_in(
    conn: Any,
    claims: Mapping[str, Any],
    *,
    allow_unverified_email: bool = False,
) -> SignInResolution:
    """Walk the resolution ladder for one verified id_token's claims.

    ``claims`` must carry ``issuer`` (or ``iss``) and ``subject`` (or
    ``sub``); ``email``, ``email_verified``, and ``name`` are optional.
    """
    issuer = str(claims.get("issuer") or claims.get("iss") or "").strip()
    subject = str(claims.get("subject") or claims.get("sub") or "").strip()
    if not issuer or not subject:
        return _refuse(
            issuer or None,
            REFUSAL_MISSING_REQUIRED_CLAIMS,
            "the id_token is missing the issuer or subject claim",
        )

    # Rung 1 — the identity is already linked.
    linked = resolve_external_identity(conn, issuer=issuer, subject=subject)
    if linked is not None:
        return _succeed(
            issuer, linked, OUTCOME_LINKED_IDENTITY,
            f"external identity is linked to actor {linked}",
        )

    email = str(claims.get("email") or "").strip()
    if not email:
        return _refuse(
            issuer,
            REFUSAL_MISSING_EMAIL_CLAIM,
            "no linked identity and the id_token carries no email claim; "
            "an operator can pre-link this identity with the identity "
            "link admin surface",
        )

    # Strict email trust: an explicit email_verified=false is never trusted;
    # an omitted claim is trusted only under the operator opt-in.
    if "email_verified" in claims:
        email_trusted = _claim_is_true(claims.get("email_verified"))
    else:
        email_trusted = allow_unverified_email
    if not email_trusted:
        return _refuse(
            issuer,
            REFUSAL_EMAIL_UNVERIFIED,
            f"the provider did not mark {email!r} verified; invites and "
            "auto-join only match verified emails",
        )

    name_claim = claims.get("name")

    # Rung 2 — a pending invite admits this email.
    invite = pending_invite_for_email(conn, email=email)
    if invite is not None:
        if invite.actor_id is not None:
            actor_id = invite.actor_id
        else:
            actor_id = _create_labelled_actor(
                conn, email=email, name_claim=name_claim,
            )
        link_external_identity(
            conn, actor_id=actor_id, issuer=issuer, subject=subject, email=email,
        )
        mark_invite_accepted(
            conn, invite_id=invite.invite_id, accepted_by_actor_id=actor_id,
        )
        _grant_invite_role(conn, invite, actor_id)
        return _succeed(
            issuer, actor_id, OUTCOME_INVITE_ACCEPTED,
            f"invite {invite.invite_id} accepted for actor {actor_id}",
        )

    # Rung 3 — the org's auto-join domain admits this email.
    org_id = default_org_id(conn)
    join_domain = auto_join_domain(conn, org_id=org_id)
    if join_domain and _email_domain(email) == join_domain:
        actor_id = _create_labelled_actor(
            conn, email=email, name_claim=name_claim,
        )
        link_external_identity(
            conn, actor_id=actor_id, issuer=issuer, subject=subject, email=email,
        )
        return _succeed(
            issuer, actor_id, OUTCOME_AUTO_JOINED,
            f"email domain {join_domain!r} auto-joined actor {actor_id}",
        )

    # Rung 4 — refuse.
    return _refuse(
        issuer,
        REFUSAL_NO_ADMISSION_MATCH,
        f"{email!r} has no linked identity, no pending invite, and does "
        "not match the org auto-join domain; an operator can invite it "
        "with the identity invite admin surface",
    )


__all__ = [
    "OUTCOME_AUTO_JOINED",
    "OUTCOME_INVITE_ACCEPTED",
    "OUTCOME_LINKED_IDENTITY",
    "OUTCOME_REFUSED",
    "REFUSAL_EMAIL_UNVERIFIED",
    "REFUSAL_MISSING_EMAIL_CLAIM",
    "REFUSAL_MISSING_REQUIRED_CLAIMS",
    "REFUSAL_NO_ADMISSION_MATCH",
    "SignInResolution",
    "resolve_sign_in",
]
