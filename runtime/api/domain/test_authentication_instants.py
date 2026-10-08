"""Credential expiry uses exact native instants in every database timezone."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain import (
    api_token_audit,
    api_tokens,
    browser_sign_in_links,
    web_sessions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identity_schema import create_external_identity_tables


START = datetime(
    1969, 12, 31, 18, 29, 59, 123456, timezone(timedelta(hours=-5, minutes=-30))
)
ZONES = ["UTC", "America/New_York", "Asia/Kolkata"]


@pytest.mark.parametrize("zone", ZONES)
def test_api_token_expiry_and_audit_preserve_microseconds(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor = seed_human_actor(test_db)
    clock = [START]
    monkeypatch.setattr(api_tokens, "_now", lambda: clock[0])
    monkeypatch.setattr(api_token_audit, "utc_now", lambda: clock[0])
    expiry = START + timedelta(microseconds=2)
    token = api_tokens.mint_token(
        test_db, actor_id=actor, name="exact-expiry", expires_at=expiry.isoformat()
    )
    row = test_db.execute(
        "SELECT created_at,expires_at,last_used_at,pg_typeof(expires_at)::text "
        "FROM api_tokens WHERE id=%s",
        (token.token_id,),
    ).fetchone()
    assert row == (START, expiry, None, "timestamp with time zone")
    clock[0] = expiry - timedelta(microseconds=1)
    assert api_tokens.verify_token(test_db, token.raw_token).actor_id == actor
    used = test_db.execute(
        "SELECT last_used_at FROM api_tokens WHERE id=%s", (token.token_id,)
    ).fetchone()[0]
    assert used == clock[0]
    clock[0] = expiry
    with pytest.raises(api_tokens.TokenExpired):
        api_tokens.verify_token(test_db, token.raw_token)
    audit = test_db.execute(
        "SELECT created_at,outcome FROM api_token_audit WHERE api_token_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (token.token_id,),
    ).fetchone()
    assert audit == (expiry, "expired")
    eternal = api_tokens.mint_token(test_db, actor_id=actor, name="no-expiry")
    assert (
        test_db.execute(
            "SELECT expires_at FROM api_tokens WHERE id=%s", (eternal.token_id,)
        ).fetchone()[0]
        is None
    )
    api_tokens.revoke_token(test_db, token_id=eternal.token_id)
    assert (
        test_db.execute(
            "SELECT revoked_at FROM api_tokens WHERE id=%s", (eternal.token_id,)
        ).fetchone()[0]
        == expiry
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
        "1970-01-01T00:00:00.1234567Z",
        datetime(1970, 1, 1),
    ],
)
def test_invalid_api_token_expiry_refuses_before_insertion(test_db, invalid):
    actor = seed_human_actor(test_db)
    before = test_db.execute("SELECT count(*) FROM api_tokens").fetchone()[0]
    with pytest.raises(InvalidInstant):
        api_tokens.mint_token(
            test_db, actor_id=actor, name="invalid-expiry", expires_at=invalid
        )
    assert test_db.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == before


@pytest.mark.parametrize("zone", ZONES)
def test_web_session_expiry_and_prune_are_exact(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor = seed_human_actor(test_db)
    clock = [START]
    monkeypatch.setattr(web_sessions, "_now_dt", lambda: clock[0])
    session = web_sessions.mint_web_session(test_db, actor_id=actor, ttl_s=1)
    expiry = START + timedelta(seconds=1)
    assert session.expires_at == format_instant(expiry)
    stored = test_db.execute(
        "SELECT created_at,expires_at FROM web_sessions WHERE id=%s",
        (session.web_session_id,),
    ).fetchone()
    assert stored == (START, expiry)
    clock[0] = expiry - timedelta(microseconds=1)
    assert web_sessions.verify_web_session(test_db, session.raw_token).actor_id == actor
    clock[0] = expiry
    with pytest.raises(web_sessions.WebSessionExpired):
        web_sessions.verify_web_session(test_db, session.raw_token)
    fresh = web_sessions.mint_web_session(test_db, actor_id=actor, ttl_s=1)
    assert (
        test_db.execute(
            "SELECT id FROM web_sessions WHERE id=%s", (session.web_session_id,)
        ).fetchone()
        is None
    )
    web_sessions.revoke_web_session(test_db, web_session_id=fresh.web_session_id)
    assert (
        test_db.execute(
            "SELECT revoked_at FROM web_sessions WHERE id=%s", (fresh.web_session_id,)
        ).fetchone()[0]
        == expiry
    )


@pytest.mark.parametrize("zone", ZONES)
def test_sign_in_link_consumption_and_expiry_are_exact(test_db, monkeypatch, zone):
    create_external_identity_tables(test_db)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor = seed_human_actor(test_db)
    clock = [START]
    monkeypatch.setattr(browser_sign_in_links, "_now", lambda: clock[0])
    monkeypatch.setattr(web_sessions, "_now_dt", lambda: clock[0])
    accepted = browser_sign_in_links.mint_browser_sign_in_link(test_db, actor_id=actor)
    expired = browser_sign_in_links.mint_browser_sign_in_link(test_db, actor_id=actor)
    expiry = START + timedelta(seconds=browser_sign_in_links.BROWSER_SIGN_IN_TTL_S)
    clock[0] = expiry - timedelta(microseconds=1)
    browser_sign_in_links.redeem_browser_sign_in_link(test_db, accepted)
    stored = test_db.execute(
        "SELECT expires_at,consumed_at,pg_typeof(consumed_at)::text "
        "FROM browser_sign_in_links WHERE selector=%s",
        (accepted.partition(".")[0],),
    ).fetchone()
    assert stored == (expiry, clock[0], "timestamp with time zone")
    with pytest.raises(browser_sign_in_links.BrowserSignInError) as replay:
        browser_sign_in_links.redeem_browser_sign_in_link(test_db, accepted)
    assert replay.value.code == "browser_sign_in_used"
    clock[0] = expiry
    with pytest.raises(browser_sign_in_links.BrowserSignInError) as edge:
        browser_sign_in_links.redeem_browser_sign_in_link(test_db, expired)
    assert edge.value.code == "browser_sign_in_expired"
    assert test_db.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 1
