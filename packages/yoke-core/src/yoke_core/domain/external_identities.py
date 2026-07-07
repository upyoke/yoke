"""External identity links and org auto-join admission.

Read/write path for ``actor_external_identities`` and the
``organizations.auto_join_domain`` column (both created in
:mod:`yoke_core.domain.external_identity_schema`).

An external identity is the pair ``(issuer, subject)`` from a *verified*
id_token; this module never verifies tokens itself — callers pass claims
that already passed signature/audience/expiry checks. The binding to an
``actors`` row is unique per pair, so :func:`resolve_external_identity`
is the authoritative sign-in lookup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.external_identity_events import (
    EVENT_AUTO_JOIN_DOMAIN_CHANGED,
    EVENT_EXTERNAL_IDENTITY_LINKED,
    emit_identity_event,
)


class ExternalIdentityError(Exception):
    """Base class for external-identity failures."""


class ExternalIdentityConflict(ExternalIdentityError):
    """The (issuer, subject) pair is already bound to a different actor."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _clean(value: Optional[str], field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExternalIdentityError(f"{field} must be non-empty")
    return text


def resolve_external_identity(
    conn: Any, *, issuer: str, subject: str,
) -> Optional[int]:
    """Return the actor id bound to ``(issuer, subject)``, or None."""
    p = _p(conn)
    row = conn.execute(
        "SELECT actor_id FROM actor_external_identities "
        f"WHERE issuer = {p} AND subject = {p}",
        (str(issuer or "").strip(), str(subject or "").strip()),
    ).fetchone()
    return int(row[0]) if row is not None else None


def link_external_identity(
    conn: Any,
    *,
    actor_id: int,
    issuer: str,
    subject: str,
    email: Optional[str] = None,
    created_by_actor_id: Optional[int] = None,
) -> int:
    """Bind ``(issuer, subject)`` to ``actor_id``; return the link row id.

    Idempotent for the same actor: re-linking an existing pair to the actor
    it already maps to returns the existing row id. A pair already bound to
    a DIFFERENT actor raises :class:`ExternalIdentityConflict` — relinking
    is a deliberate operator act (revoke/delete first), never silent.
    """
    issuer = _clean(issuer, "issuer")
    subject = _clean(subject, "subject")
    p = _p(conn)
    row = conn.execute(
        "SELECT id, actor_id FROM actor_external_identities "
        f"WHERE issuer = {p} AND subject = {p}",
        (issuer, subject),
    ).fetchone()
    if row is not None:
        existing_id, existing_actor = int(row[0]), int(row[1])
        if existing_actor != int(actor_id):
            raise ExternalIdentityConflict(
                f"identity ({issuer!r}, {subject!r}) is already linked to "
                f"actor {existing_actor}"
            )
        return existing_id
    cur = conn.execute(
        "INSERT INTO actor_external_identities "
        "(actor_id, issuer, subject, email, linked_at, created_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (
            int(actor_id),
            issuer,
            subject,
            (str(email).strip() or None) if email else None,
            _now(),
            created_by_actor_id,
        ),
    )
    link_id = int(cur.fetchone()[0])
    conn.commit()
    emit_identity_event(
        EVENT_EXTERNAL_IDENTITY_LINKED,
        context={
            "actor_id": int(actor_id),
            "issuer": issuer,
            "email": email,
            "created_by_actor_id": created_by_actor_id,
        },
    )
    return link_id


def default_org_id(conn: Any) -> int:
    """Return the universe's identity-card org (the lowest-id row).

    Matches the single-card convention the local-universe birth path and
    the ``organizations.get`` handler use.
    """
    row = conn.execute(
        "SELECT id FROM organizations ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        raise ExternalIdentityError("no organization exists on this universe")
    return int(row[0])


def normalize_email_domain(value: Optional[str]) -> Optional[str]:
    """Case-fold a domain and drop a leading ``@``; empty input -> None."""
    text = str(value or "").strip().lower().lstrip("@")
    return text or None


def auto_join_domain(conn: Any, *, org_id: int) -> Optional[str]:
    """Return the org's auto-join email domain, or None when unset."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT auto_join_domain FROM organizations WHERE id = {p}",
        (int(org_id),),
    ).fetchone()
    if row is None:
        raise ExternalIdentityError(f"organization {org_id} does not exist")
    value = row[0]
    return normalize_email_domain(value) if value else None


def set_auto_join_domain(
    conn: Any,
    *,
    org_id: int,
    domain: Optional[str],
    changed_by_actor_id: Optional[int] = None,
) -> Optional[str]:
    """Set (or clear, with ``domain=None``/empty) the org's auto-join domain.

    Returns the normalized stored value. Emits ``AutoJoinDomainChanged``
    naming both the previous and the new value so the audit trail shows
    every widening or narrowing of the admission surface.
    """
    previous = auto_join_domain(conn, org_id=org_id)
    normalized = normalize_email_domain(domain)
    p = _p(conn)
    conn.execute(
        f"UPDATE organizations SET auto_join_domain = {p} WHERE id = {p}",
        (normalized, int(org_id)),
    )
    conn.commit()
    emit_identity_event(
        EVENT_AUTO_JOIN_DOMAIN_CHANGED,
        severity="STATUS",
        context={
            "org_id": int(org_id),
            "previous_domain": previous,
            "domain": normalized,
            "changed_by_actor_id": changed_by_actor_id,
        },
    )
    return normalized


__all__ = [
    "ExternalIdentityConflict",
    "ExternalIdentityError",
    "auto_join_domain",
    "default_org_id",
    "link_external_identity",
    "normalize_email_domain",
    "resolve_external_identity",
    "set_auto_join_domain",
]
