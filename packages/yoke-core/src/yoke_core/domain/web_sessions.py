"""Browser web-session tokens for the self-host sign-in door.

Mirrors the :mod:`yoke_core.domain.api_tokens` shape: a DB-backed random
token whose SHA-256 hash is the only stored value — the raw token is
returned once at mint time (it becomes the session cookie value) and is
never persisted or logged. Unlike API tokens, web sessions always carry
an expiry, and verification touches ``last_used_at``.

Web sessions authorize READ-ONLY browser surfaces only; every write
still requires a bearer API token. That policy lives at the HTTP layer —
this module only answers "which actor does this cookie belong to, and is
it still live?".
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend


#: Default browser-session lifetime. One value, consumed by the mint
#: helper and the HTTP cookie Max-Age alike.
DEFAULT_WEB_SESSION_TTL_S = 7 * 24 * 3600


class WebSessionError(Exception):
    """Base class for web-session verification failures."""


class WebSessionNotFound(WebSessionError):
    """No stored session hash matched the supplied raw token."""


class WebSessionRevoked(WebSessionError):
    """The stored session is revoked."""


class WebSessionExpired(WebSessionError):
    """The stored session has passed its expiry timestamp."""


@dataclass(frozen=True)
class CreatedWebSession:
    web_session_id: int
    actor_id: int
    raw_token: str
    expires_at: str


@dataclass(frozen=True)
class VerifiedWebSession:
    web_session_id: int
    actor_id: int


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def generate_web_session_token() -> str:
    """Generate a new raw session token. Returned once; never persisted raw."""
    return secrets.token_urlsafe(32)


def hash_web_session_token(raw_token: str) -> str:
    """Return the non-reversible hash stored for ``raw_token``."""
    if not raw_token or not str(raw_token).strip():
        raise ValueError("web-session token must be non-empty")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _prune_expired(conn: Any, *, now: datetime) -> None:
    """Best-effort delete of rows already past expiry. Never raises."""
    p = _p(conn)
    try:
        conn.execute(
            f"DELETE FROM web_sessions WHERE expires_at <= {p}", (_fmt(now),),
        )
    except Exception:  # noqa: BLE001 - a housekeeping sweep never blocks a mint
        pass


def mint_web_session(
    conn: Any,
    *,
    actor_id: int,
    ttl_s: int = DEFAULT_WEB_SESSION_TTL_S,
    raw_token: str | None = None,
) -> CreatedWebSession:
    """Create a live web session and return its raw token once."""
    if ttl_s <= 0:
        raise ValueError(f"web-session ttl_s must be positive, got {ttl_s}")
    raw = raw_token or generate_web_session_token()
    token_hash = hash_web_session_token(raw)
    now = _now_dt()
    expires_at = _fmt(now + timedelta(seconds=int(ttl_s)))
    p = _p(conn)
    # Opportunistic bound: sweep already-expired rows so the table does not
    # grow one dead row per browser sign-in for the life of the door. Cheap
    # (indexed on the same timestamp column verify compares) and best-effort
    # — a sweep failure never blocks minting the new session.
    _prune_expired(conn, now=now)
    row = conn.execute(
        "INSERT INTO web_sessions (token_hash, actor_id, created_at, expires_at) "
        f"VALUES ({p}, {p}, {p}, {p}) RETURNING id",
        (token_hash, int(actor_id), _fmt(now), expires_at),
    ).fetchone()
    conn.commit()
    return CreatedWebSession(
        web_session_id=int(row[0]),
        actor_id=int(actor_id),
        raw_token=raw,
        expires_at=expires_at,
    )


def verify_web_session(conn: Any, raw_token: str) -> VerifiedWebSession:
    """Verify a raw session token, touch ``last_used_at``, return the actor.

    Raises :class:`WebSessionNotFound` / :class:`WebSessionRevoked` /
    :class:`WebSessionExpired`; the HTTP layer maps all three to the same
    signed-out treatment so a probing client learns nothing from the split.
    """
    token_hash = hash_web_session_token(raw_token)
    p = _p(conn)
    row = conn.execute(
        "SELECT id, actor_id, expires_at, revoked_at "
        f"FROM web_sessions WHERE token_hash = {p}",
        (token_hash,),
    ).fetchone()
    if row is None:
        raise WebSessionNotFound("web session not found")
    web_session_id, actor_id, expires_at, revoked_at = row
    if revoked_at is not None:
        raise WebSessionRevoked("web session is revoked")
    if str(expires_at) <= _fmt(_now_dt()):
        raise WebSessionExpired("web session is expired")
    conn.execute(
        f"UPDATE web_sessions SET last_used_at = {p} WHERE id = {p}",
        (_fmt(_now_dt()), int(web_session_id)),
    )
    conn.commit()
    return VerifiedWebSession(
        web_session_id=int(web_session_id), actor_id=int(actor_id),
    )


def revoke_web_session(conn: Any, *, web_session_id: int) -> None:
    """Revoke a session by row id; raw token material is not needed."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM web_sessions WHERE id = {p}", (int(web_session_id),),
    ).fetchone()
    if row is None:
        raise WebSessionNotFound(f"web session id {web_session_id} not found")
    conn.execute(
        f"UPDATE web_sessions SET revoked_at = {p} "
        f"WHERE id = {p} AND revoked_at IS NULL",
        (_fmt(_now_dt()), int(web_session_id)),
    )
    conn.commit()


__all__ = [
    "CreatedWebSession",
    "DEFAULT_WEB_SESSION_TTL_S",
    "VerifiedWebSession",
    "WebSessionError",
    "WebSessionExpired",
    "WebSessionNotFound",
    "WebSessionRevoked",
    "generate_web_session_token",
    "hash_web_session_token",
    "mint_web_session",
    "revoke_web_session",
    "verify_web_session",
]
