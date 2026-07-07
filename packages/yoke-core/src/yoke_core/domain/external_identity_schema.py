"""Schema DDL for external sign-in identity.

Owns the three additive tables behind the self-host OIDC sign-in door,
plus the org auto-join column:

* ``actor_external_identities`` — one row per verified external identity
  (``issuer`` + ``subject`` from a verified id_token) bound to an
  ``actors`` row. ``UNIQUE(issuer, subject)`` makes the binding the
  authoritative sign-in lookup. ``email`` is a convenience copy of the
  verified email at link time, never an identity key.
* ``actor_invites`` — operator-authored admission records. A pending
  invite admits a verified email into the org; ``role_id`` optionally
  grants an org role on acceptance; ``actor_id`` optionally targets an
  EXISTING actor (an email pre-link) so acceptance binds the identity to
  that actor instead of creating a new one. At most one pending invite
  per case-folded email per org (partial unique index).
* ``web_sessions`` — DB-backed hashed browser session tokens, mirroring
  the ``api_tokens`` shape (SHA-256 of a random token; the raw value is
  returned once and never persisted).

``organizations.auto_join_domain`` (nullable TEXT) admits any verified
email under the named domain without an invite.

All shapes are additive: the schema-init chain applies them idempotently
on every server boot, so every born universe converges on next start.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


REQUIRED_EXTERNAL_IDENTITY_TABLES = (
    "actor_external_identities",
    "actor_invites",
    "web_sessions",
)


def create_external_identity_tables(conn: Any) -> None:
    """Create the external sign-in identity tables and indexes, idempotently."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS actor_external_identities (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            issuer TEXT NOT NULL,
            subject TEXT NOT NULL,
            email TEXT,
            linked_at TEXT NOT NULL,
            created_by_actor_id INTEGER REFERENCES actors(id),
            UNIQUE(issuer, subject)
        );
        CREATE INDEX IF NOT EXISTS idx_actor_external_identities_actor
            ON actor_external_identities(actor_id);

        CREATE TABLE IF NOT EXISTS actor_invites (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            role_id INTEGER REFERENCES roles(id),
            actor_id INTEGER REFERENCES actors(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','accepted','revoked')),
            invited_by_actor_id INTEGER NOT NULL REFERENCES actors(id),
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            accepted_by_actor_id INTEGER REFERENCES actors(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_actor_invites_pending_email
            ON actor_invites(lower(email), org_id)
            WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_actor_invites_org
            ON actor_invites(org_id);

        CREATE TABLE IF NOT EXISTS web_sessions (
            id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            last_used_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_web_sessions_actor
            ON web_sessions(actor_id);
    """)
    conn.commit()
    # organizations always precedes this module in the init chain
    # (create_auth_tables -> create_org_tables), so the auto-join column
    # ALTER is safe here and both fresh-init and re-init converge.
    _add_column_if_not_exists(
        conn, "organizations", "auto_join_domain", "TEXT DEFAULT NULL",
    )
    conn.commit()


def required_tables() -> tuple[str, ...]:
    return REQUIRED_EXTERNAL_IDENTITY_TABLES


__all__ = [
    "REQUIRED_EXTERNAL_IDENTITY_TABLES",
    "create_external_identity_tables",
    "required_tables",
]
