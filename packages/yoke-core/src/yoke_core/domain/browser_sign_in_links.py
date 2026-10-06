"""Hashed, short-lived browser admission links, shared by server workers.

Links are separate from web sessions: possessing an unredeemed link cannot
authorize a cookie request. A conditional UPDATE consumes a link exactly once
in the same transaction that mints its normal web session.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from yoke_contracts.browser_sign_in import BROWSER_SIGN_IN_MAX_LENGTH

from yoke_core.domain import db_backend
from yoke_core.domain.actor_state import require_actor_active
from yoke_core.domain.web_sessions import CreatedWebSession, mint_web_session

BROWSER_SIGN_IN_TTL_S = 120


class BrowserSignInError(ValueError):
    """A browser admission link cannot be redeemed."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"{code}: run `yoke ui up` again to get a new sign-in link")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def mint_browser_sign_in_link(conn: Any, *, actor_id: int) -> str:
    """Return a random code once; persist only its hash and admission state."""
    require_actor_active(conn, actor_id, lock=True)
    now = _now()
    selector = secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    p = _p(conn)
    conn.execute(
        f"DELETE FROM browser_sign_in_links WHERE expires_at <= {p}",
        (_fmt(now),),
    )
    conn.execute(
        "INSERT INTO browser_sign_in_links (selector, code_hash, actor_id, expires_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (
            selector,
            _hash(secret),
            actor_id,
            _fmt(now + timedelta(seconds=BROWSER_SIGN_IN_TTL_S)),
        ),
    )
    conn.commit()
    return selector + "." + secret


def redeem_browser_sign_in_link(conn: Any, code: str) -> CreatedWebSession:
    """Consume once and mint a session; competing workers cannot both win."""
    if not code or len(code) > BROWSER_SIGN_IN_MAX_LENGTH:
        raise BrowserSignInError("browser_sign_in_invalid")
    p = _p(conn)
    now = _fmt(_now())
    selector, separator, secret = code.partition(".")
    row = conn.execute(
        f"SELECT code_hash FROM browser_sign_in_links WHERE selector = {p}",
        (selector,),
    ).fetchone()
    stored_hash = str(row[0]) if row is not None else "0" * 64
    matched = hmac.compare_digest(stored_hash, _hash(secret))
    if row is None or not separator or not matched:
        conn.rollback()
        raise BrowserSignInError("browser_sign_in_invalid")
    row = conn.execute(
        f"UPDATE browser_sign_in_links SET consumed_at = {p} "
        f"WHERE selector = {p} AND consumed_at IS NULL AND expires_at > {p} "
        "RETURNING actor_id",
        (now, selector, now),
    ).fetchone()
    if row is None:
        row = conn.execute(
            f"SELECT expires_at, consumed_at FROM browser_sign_in_links WHERE selector = {p}",
            (selector,),
        ).fetchone()
        conn.rollback()
        reason = "browser_sign_in_invalid"
        if row is not None:
            reason = "browser_sign_in_used" if row[1] else "browser_sign_in_expired"
        raise BrowserSignInError(reason)
    return mint_web_session(conn, actor_id=int(row[0]))
