"""Atomic credential rotation for restored self-host universes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import psycopg

from yoke_core.domain import json_helper
from yoke_core.domain.actor_permissions import ROLE_ADMIN
from yoke_core.domain.actors import GITHUB_LABEL_SURFACE
from yoke_core.domain.api_tokens import (
    DEFAULT_ADMIN_ACTOR_LABEL,
    generate_token,
    hash_token,
)


IMPORTED_ADMIN_TOKEN_NAME = "self-host-import-admin"
RECOVERY_ADMIN_TOKEN_NAME = "self-host-recovery"
_ORG_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$", re.ASCII)


class UniverseImportCredentialError(RuntimeError):
    """A restored universe could not establish usable admin authority."""


@dataclass(frozen=True)
class ImportedCredential:
    org_slug: str
    actor_id: int
    token_id: int
    raw_token: str
    revoked_token_count: int
    revoked_web_session_count: int


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_import_admin(conn: psycopg.Connection, *, now: str) -> int:
    row = conn.execute(
        "SELECT a.id, a.kind FROM actor_labels al "
        "JOIN actors a ON a.id = al.actor_id "
        "WHERE al.surface = %s AND al.label = %s",
        (GITHUB_LABEL_SURFACE, DEFAULT_ADMIN_ACTOR_LABEL),
    ).fetchone()
    if row is not None:
        if str(row[1]) != "human":
            raise UniverseImportCredentialError(
                "the imported admin label belongs to a non-human actor"
            )
        return int(row[0])

    actor_row = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('human', NULL, %s) RETURNING id",
        (now,),
    ).fetchone()
    if actor_row is None:
        raise UniverseImportCredentialError(
            "the import admin actor could not be created"
        )
    actor_id = int(actor_row[0])
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        "VALUES (%s, %s, %s, %s)",
        (actor_id, GITHUB_LABEL_SURFACE, DEFAULT_ADMIN_ACTOR_LABEL, now),
    )
    return actor_id


def _resolve_authority(conn: psycopg.Connection, *, now: str) -> tuple[str, int]:
    organizations = conn.execute(
        "SELECT id, slug FROM organizations ORDER BY id"
    ).fetchall()
    if len(organizations) != 1:
        raise UniverseImportCredentialError(
            "a self-host import requires exactly one organization; "
            f"the archive contains {len(organizations)}"
        )
    org_id, raw_slug = int(organizations[0][0]), organizations[0][1]
    if not isinstance(raw_slug, str) or _ORG_SLUG_RE.fullmatch(raw_slug) is None:
        raise UniverseImportCredentialError(
            "the imported organization slug is not a bounded safe identifier"
        )
    org_slug = raw_slug
    role_row = conn.execute(
        "SELECT id FROM roles WHERE name = %s",
        (ROLE_ADMIN,),
    ).fetchone()
    if role_row is None:
        raise UniverseImportCredentialError("the imported universe has no admin role")
    actor_id = _resolve_import_admin(conn, now=now)
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT(actor_id, org_id, role_id) DO NOTHING",
        (actor_id, org_id, int(role_row[0]), now, actor_id),
    )
    return org_slug, actor_id


def _revoke_selected_tokens(
    conn: psycopg.Connection,
    *,
    where_sql: str,
    where_params: Sequence[object],
    actor_id: int,
    metadata: str,
    now: str,
) -> int:
    revoked_row = conn.execute(
        "WITH revoked AS ("
        "UPDATE api_tokens SET status = 'revoked', revoked_at = %s WHERE "
        + where_sql
        + " RETURNING id"
        "), audited AS ("
        "INSERT INTO api_token_audit "
        "(api_token_id, actor_id, project_id, event_type, outcome, "
        "permission_key, diagnostic_metadata, created_at) "
        "SELECT id, %s, NULL, 'revoked', 'success', NULL, %s, %s FROM revoked "
        "RETURNING 1"
        ") SELECT COUNT(*) FROM audited",
        (now, *where_params, actor_id, metadata, now),
    ).fetchone()
    return int(revoked_row[0]) if revoked_row is not None else 0


def _mint_replacement(
    conn: psycopg.Connection,
    *,
    org_slug: str,
    actor_id: int,
    token_name: str,
    metadata: str,
    now: str,
    revoked_token_count: int,
    revoked_web_session_count: int,
) -> ImportedCredential:
    raw_token = generate_token()
    token_row = conn.execute(
        "INSERT INTO api_tokens "
        "(token_hash, actor_id, name, status, created_at, expires_at, "
        "diagnostic_metadata) "
        "VALUES (%s, %s, %s, 'active', %s, NULL, %s) RETURNING id",
        (hash_token(raw_token), actor_id, token_name, now, metadata),
    ).fetchone()
    if token_row is None:
        raise UniverseImportCredentialError(
            "the replacement admin token could not be created"
        )
    token_id = int(token_row[0])
    conn.execute(
        "INSERT INTO api_token_audit "
        "(api_token_id, actor_id, project_id, event_type, outcome, "
        "permission_key, diagnostic_metadata, created_at) "
        "VALUES (%s, %s, NULL, 'issued', 'success', NULL, %s, %s)",
        (token_id, actor_id, metadata, now),
    )
    return ImportedCredential(
        org_slug=org_slug,
        actor_id=actor_id,
        token_id=token_id,
        raw_token=raw_token,
        revoked_token_count=revoked_token_count,
        revoked_web_session_count=revoked_web_session_count,
    )


def _rotate(
    conn: psycopg.Connection,
    *,
    token_name: str,
    reason: str,
    where_sql: str,
    where_params: Sequence[object] = (),
    revoke_web_sessions: bool = False,
) -> ImportedCredential:
    now = _now()
    org_slug, actor_id = _resolve_authority(conn, now=now)
    metadata = json_helper.dumps_compact({"reason": reason})
    revoked_token_count = _revoke_selected_tokens(
        conn,
        where_sql=where_sql,
        where_params=where_params,
        actor_id=actor_id,
        metadata=metadata,
        now=now,
    )
    revoked_web_session_count = 0
    if revoke_web_sessions:
        session_row = conn.execute(
            "WITH revoked AS ("
            "UPDATE web_sessions SET revoked_at = %s "
            "WHERE revoked_at IS NULL RETURNING 1"
            ") SELECT COUNT(*) FROM revoked",
            (now,),
        ).fetchone()
        revoked_web_session_count = (
            int(session_row[0]) if session_row is not None else 0
        )
    return _mint_replacement(
        conn,
        org_slug=org_slug,
        actor_id=actor_id,
        token_name=token_name,
        metadata=metadata,
        now=now,
        revoked_token_count=revoked_token_count,
        revoked_web_session_count=revoked_web_session_count,
    )


def replace_imported_credentials(
    conn: psycopg.Connection,
) -> ImportedCredential:
    """Revoke every active imported token and mint one usable replacement."""
    return _rotate(
        conn,
        token_name=IMPORTED_ADMIN_TOKEN_NAME,
        reason="self_host_import_credential_handoff",
        where_sql="status = 'active'",
        revoke_web_sessions=True,
    )


def recover_import_credential(conn: psycopg.Connection) -> ImportedCredential:
    """Rotate only prior import/recovery tokens after one-time output loss."""
    return _rotate(
        conn,
        token_name=RECOVERY_ADMIN_TOKEN_NAME,
        reason="self_host_import_credential_recovery",
        where_sql="status = 'active' AND name IN (%s, %s)",
        where_params=(IMPORTED_ADMIN_TOKEN_NAME, RECOVERY_ADMIN_TOKEN_NAME),
    )


__all__ = [
    "IMPORTED_ADMIN_TOKEN_NAME",
    "RECOVERY_ADMIN_TOKEN_NAME",
    "ImportedCredential",
    "UniverseImportCredentialError",
    "recover_import_credential",
    "replace_imported_credentials",
]
