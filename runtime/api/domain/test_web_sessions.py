"""Web-session token semantics: hash storage, expiry, revocation."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import (
    create_external_identity_tables,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.web_sessions import (
    WebSessionExpired,
    WebSessionNotFound,
    WebSessionRevoked,
    mint_web_session,
    revoke_web_session,
    verify_web_session,
)


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        create_external_identity_tables(c)
        seed_default_org(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_mint_stores_hash_only_and_verify_touches_last_used(conn):
    actor_id = seed_human_actor(conn)
    created = mint_web_session(conn, actor_id=actor_id)

    stored = conn.execute(
        "SELECT token_hash, last_used_at FROM web_sessions WHERE id = %s",
        (created.web_session_id,),
    ).fetchone()
    assert stored[0] != created.raw_token
    assert created.raw_token not in stored[0]
    assert stored[1] is None

    verified = verify_web_session(conn, created.raw_token)
    assert verified.actor_id == actor_id
    assert verified.web_session_id == created.web_session_id

    touched = conn.execute(
        "SELECT last_used_at FROM web_sessions WHERE id = %s",
        (created.web_session_id,),
    ).fetchone()
    assert touched[0] is not None


def test_unknown_token_raises_not_found(conn):
    with pytest.raises(WebSessionNotFound):
        verify_web_session(conn, "never-minted-token")


def test_expired_session_is_refused(conn):
    actor_id = seed_human_actor(conn)
    created = mint_web_session(conn, actor_id=actor_id)
    conn.execute(
        "UPDATE web_sessions SET expires_at = '2000-01-01T00:00:00Z' "
        "WHERE id = %s",
        (created.web_session_id,),
    )
    conn.commit()
    with pytest.raises(WebSessionExpired):
        verify_web_session(conn, created.raw_token)


def test_revoked_session_is_refused(conn):
    actor_id = seed_human_actor(conn)
    created = mint_web_session(conn, actor_id=actor_id)
    revoke_web_session(conn, web_session_id=created.web_session_id)
    with pytest.raises(WebSessionRevoked):
        verify_web_session(conn, created.raw_token)
    with pytest.raises(WebSessionNotFound):
        revoke_web_session(conn, web_session_id=99999)


def test_mint_prunes_expired_rows(conn):
    actor_id = seed_human_actor(conn)
    stale = mint_web_session(conn, actor_id=actor_id)
    conn.execute(
        "UPDATE web_sessions SET expires_at = '2000-01-01T00:00:00Z' "
        "WHERE id = %s",
        (stale.web_session_id,),
    )
    conn.commit()
    # Minting a fresh session sweeps the already-expired row so the table
    # stays bounded across the life of the door.
    fresh = mint_web_session(conn, actor_id=actor_id)
    rows = conn.execute("SELECT id FROM web_sessions").fetchall()
    ids = {row[0] for row in rows}
    assert stale.web_session_id not in ids
    assert fresh.web_session_id in ids


def test_ttl_must_be_positive_and_expiry_lands_in_future(conn):
    actor_id = seed_human_actor(conn)
    with pytest.raises(ValueError):
        mint_web_session(conn, actor_id=actor_id, ttl_s=0)
    created = mint_web_session(conn, actor_id=actor_id, ttl_s=60)
    row = conn.execute(
        "SELECT created_at, expires_at FROM web_sessions WHERE id = %s",
        (created.web_session_id,),
    ).fetchone()
    assert str(row[1]) > str(row[0])
