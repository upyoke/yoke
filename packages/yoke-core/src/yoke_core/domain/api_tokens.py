"""Actor-bound API token helpers for the cloud-runtime cloud auth substrate."""

from __future__ import annotations

import hashlib
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_core.domain import db_backend, json_helper


TOKEN_PREFIX = "yoke_v1_"
TOKEN_STATUS_ACTIVE = "active"
TOKEN_STATUS_REVOKED = "revoked"

# Neutral defaults for the first-admin bootstrap: the admin actor label and
# the name of the one token minted for it.
DEFAULT_ADMIN_ACTOR_LABEL = "admin"
INITIAL_ADMIN_TOKEN_NAME = "initial-admin"

# Dash-free base62 body alphabet: a '-' is a word boundary, so a token
# containing one cannot be selected with a single double-click in terminals
# or browsers. The fixed prefix keeps only '_', which IS a word character.
_TOKEN_BODY_ALPHABET = string.ascii_letters + string.digits
_TOKEN_BODY_LEN = 43  # matches the entropy of the prior secrets.token_urlsafe(32) body


class TokenError(Exception):
    """Base class for token verification failures."""


class TokenNotFound(TokenError):
    """No stored token hash matched the supplied raw token."""


class TokenRevoked(TokenError):
    """The stored token is revoked."""


class TokenExpired(TokenError):
    """The stored token has passed its expiry timestamp."""


@dataclass(frozen=True)
class CreatedToken:
    token_id: int
    actor_id: int
    raw_token: str


@dataclass(frozen=True)
class VerifiedToken:
    token_id: int
    actor_id: int
    name: str


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hash_token(raw_token: str) -> str:
    """Return the non-reversible hash stored for ``raw_token``."""
    if not raw_token or not raw_token.startswith(TOKEN_PREFIX):
        raise ValueError(f"API token must start with {TOKEN_PREFIX!r}")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Generate a new raw API token. Returned once; never persisted raw.

    The random body uses a dash-free base62 alphabet so the entire token is a
    single double-click-selectable word.
    """
    body = "".join(secrets.choice(_TOKEN_BODY_ALPHABET) for _ in range(_TOKEN_BODY_LEN))
    return TOKEN_PREFIX + body


def _metadata_json(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    ordered = {key: metadata[key] for key in sorted(metadata)}
    return json_helper.dumps_compact(ordered)


def mint_token(
    conn: Any,
    *,
    actor_id: int,
    name: str,
    raw_token: str | None = None,
    expires_at: str | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> CreatedToken:
    """Create an active actor-bound token and return its raw value once."""
    raw = raw_token or generate_token()
    token_hash = hash_token(raw)
    p = _p(conn)
    row = conn.execute(
        "INSERT INTO api_tokens "
        "(token_hash, actor_id, name, status, created_at, expires_at, diagnostic_metadata) "
        f"VALUES ({p}, {p}, {p}, 'active', {p}, {p}, {p}) "
        "RETURNING id",
        (
            token_hash,
            actor_id,
            name,
            _now(),
            expires_at,
            _metadata_json(diagnostic_metadata),
        ),
    ).fetchone()
    conn.commit()
    token_id = int(row[0])
    record_token_audit(
        conn,
        api_token_id=token_id,
        actor_id=actor_id,
        event_type="issued",
        outcome="success",
    )
    return CreatedToken(token_id=token_id, actor_id=actor_id, raw_token=raw)


def verify_token(
    conn: Any,
    raw_token: str,
    *,
    project_id: int | None = None,
    permission_key: str | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> VerifiedToken:
    """Verify a raw token, update use audit, and return actor identity."""
    token_hash = hash_token(raw_token)
    p = _p(conn)
    row = conn.execute(
        "SELECT id, actor_id, name, status, expires_at "
        f"FROM api_tokens WHERE token_hash = {p}",
        (token_hash,),
    ).fetchone()
    if row is None:
        record_token_audit(
            conn,
            api_token_id=None,
            actor_id=None,
            project_id=project_id,
            event_type="verify",
            outcome="not_found",
            permission_key=permission_key,
            diagnostic_metadata=diagnostic_metadata,
        )
        raise TokenNotFound("API token not found")
    token_id, actor_id, name, status, expires_at = row
    token_id = int(token_id)
    actor_id = int(actor_id)
    if status != TOKEN_STATUS_ACTIVE:
        record_token_audit(
            conn,
            api_token_id=token_id,
            actor_id=actor_id,
            project_id=project_id,
            event_type="verify",
            outcome="revoked",
            permission_key=permission_key,
            diagnostic_metadata=diagnostic_metadata,
        )
        raise TokenRevoked("API token is revoked")
    if expires_at and str(expires_at) <= _now():
        record_token_audit(
            conn,
            api_token_id=token_id,
            actor_id=actor_id,
            project_id=project_id,
            event_type="verify",
            outcome="expired",
            permission_key=permission_key,
            diagnostic_metadata=diagnostic_metadata,
        )
        raise TokenExpired("API token is expired")
    conn.execute(
        f"UPDATE api_tokens SET last_used_at = {p} WHERE id = {p}",
        (_now(), token_id),
    )
    conn.commit()
    record_token_audit(
        conn,
        api_token_id=token_id,
        actor_id=actor_id,
        project_id=project_id,
        event_type="verify",
        outcome="success",
        permission_key=permission_key,
        diagnostic_metadata=diagnostic_metadata,
    )
    return VerifiedToken(token_id=token_id, actor_id=actor_id, name=str(name))


def revoke_token(conn: Any, *, token_id: int, actor_id: int | None = None) -> None:
    """Revoke a token by id; raw token material is not needed."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT actor_id FROM api_tokens WHERE id = {p}",
        (token_id,),
    ).fetchone()
    if row is None:
        raise TokenNotFound(f"API token id {token_id} not found")
    token_actor_id = int(row[0])
    conn.execute(
        f"UPDATE api_tokens SET status = 'revoked', revoked_at = {p} WHERE id = {p}",
        (_now(), token_id),
    )
    conn.commit()
    record_token_audit(
        conn,
        api_token_id=token_id,
        actor_id=actor_id or token_actor_id,
        event_type="revoked",
        outcome="success",
    )


def record_token_audit(
    conn: Any,
    *,
    api_token_id: int | None,
    actor_id: int | None,
    event_type: str,
    outcome: str,
    project_id: int | None = None,
    permission_key: str | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> None:
    """Append a non-secret auth audit row."""
    p = _p(conn)
    conn.execute(
        "INSERT INTO api_token_audit "
        "(api_token_id, actor_id, project_id, event_type, outcome, "
        "permission_key, diagnostic_metadata, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            api_token_id,
            actor_id,
            project_id,
            event_type,
            outcome,
            permission_key,
            _metadata_json(diagnostic_metadata),
            _now(),
        ),
    )
    conn.commit()


def bootstrap_admin_token(
    conn: Any,
    *,
    actor_label: str = DEFAULT_ADMIN_ACTOR_LABEL,
    project: str | None = None,
    token_name: str = INITIAL_ADMIN_TOKEN_NAME,
) -> CreatedToken:
    """Compatibility surface for the admin token bootstrap owner."""
    from yoke_core.domain.api_token_bootstrap import bootstrap_admin_token as run

    return run(
        conn,
        actor_label=actor_label,
        project=project,
        token_name=token_name,
    )


def bootstrap_project_service_token(
    conn: Any,
    *,
    system_component: str,
    project: str | int,
    role_name: str,
    token_name: str,
) -> CreatedToken:
    """Compatibility surface for project service-identity bootstrap."""
    from yoke_core.domain.api_token_bootstrap import (
        bootstrap_project_service_token as run,
    )

    return run(
        conn,
        system_component=system_component,
        project=project,
        role_name=role_name,
        token_name=token_name,
    )


__all__ = [
    "CreatedToken",
    "DEFAULT_ADMIN_ACTOR_LABEL",
    "INITIAL_ADMIN_TOKEN_NAME",
    "TOKEN_PREFIX",
    "TOKEN_STATUS_ACTIVE",
    "TOKEN_STATUS_REVOKED",
    "TokenError",
    "TokenExpired",
    "TokenNotFound",
    "TokenRevoked",
    "VerifiedToken",
    "bootstrap_admin_token",
    "bootstrap_project_service_token",
    "generate_token",
    "hash_token",
    "mint_token",
    "record_token_audit",
    "revoke_token",
    "verify_token",
]
