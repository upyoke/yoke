"""Ordered migration coverage for retiring the core system actor.

The fixture is a freshly born universe, which by construction no longer
carries the core actor, re-shaped by hand into the older universe the entry
converts: the two relaxed columns put back to NOT NULL and a ``yoke-core``
system actor attributed on every reference it ever held.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.file_test_db import (
    apply_booted_schema,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.actor_invites import create_invite, get_invite
from yoke_core.domain.actor_permissions import role_id_by_name, seed_roles_and_permissions
from yoke_core.domain.actors import seed_system_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.org_schema import seed_default_org

ENTRY_NAME = "0072_retire_core_system_actor"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _entry():
    record = next(
        candidate
        for candidate in ordered_entries(history_dir(migration_history_package))
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


@pytest.fixture
def universe(tmp_path, monkeypatch):
    with init_test_db(tmp_path, apply_schema=apply_booted_schema) as path:
        monkeypatch.setenv("YOKE_DB", path)
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()


def _nullable(conn, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "AND column_name = %s",
        (table, column),
    ).fetchone()
    return row[0] == "YES"


def _source_default(conn):
    return conn.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'items' "
        "AND column_name = 'source'"
    ).fetchone()[0]


def _older_universe(conn) -> dict[str, int]:
    for table, column in entry.RELAXED_COLUMNS:
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL")
    conn.execute("ALTER TABLE items ALTER COLUMN source SET DEFAULT '2'")
    seed_roles_and_permissions(conn)
    org_id = seed_default_org(conn)
    human = int(conn.execute("SELECT min(id) FROM actors WHERE kind = 'human'").fetchone()[0])
    core = seed_system_actor(conn, entry.CORE_COMPONENT)
    admin = role_id_by_name(conn, "admin")
    conn.execute(
        "INSERT INTO actor_org_roles (actor_id, org_id, role_id, granted_at, "
        "granted_by_actor_id) VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s) "
        "ON CONFLICT (actor_id, org_id, role_id) DO UPDATE "
        "SET granted_by_actor_id = EXCLUDED.granted_by_actor_id",
        (core, org_id, admin, NOW, core, human, org_id, admin, NOW, core),
    )
    invite = create_invite(
        conn, email="invited@example.com", org_id=org_id, invited_by_actor_id=core
    )
    conn.execute(
        "INSERT INTO session_messages (message_id, sender_actor_id, body, "
        "body_sha256, selector_snapshot, idempotency_key, created_at, "
        "expires_at, cancelled_at, cancelled_by_actor_id) "
        "VALUES ('engine-notice', %s, 'wake', 'digest', '{}', "
        "'desktop-operator-wake:env:session', %s, %s, %s, %s)",
        (core, NOW, NOW + timedelta(hours=1), NOW, core),
    )
    conn.commit()
    return {"core": core, "human": human, "org": org_id, "invite": invite.invite_id}


def test_entry_declares_the_next_release_floor() -> None:
    assert declared_minimum(entry) == NEXT_RELEASE


def test_born_universe_has_no_core_actor_and_its_human_is_id_one(universe) -> None:
    rows = universe.execute("SELECT id, kind FROM actors ORDER BY id").fetchall()
    assert rows[0] == (1, "human")
    assert entry._core_actor_id(universe) is None
    for table, column in entry.RELAXED_COLUMNS:
        assert _nullable(universe, table, column)
    assert _source_default(universe) == entry.ITEM_SOURCE_DEFAULT
    entry.invariants(universe)


def test_older_universe_converges_and_rerun_is_a_no_op(universe) -> None:
    ids = _older_universe(universe)
    entry.apply(universe)
    universe.commit()
    entry.invariants(universe)
    assert entry._core_actor_id(universe) is None
    assert universe.execute(
        "SELECT sender_actor_id, cancelled_by_actor_id FROM session_messages "
        "WHERE message_id = 'engine-notice'"
    ).fetchone() == (None, None)
    assert universe.execute(
        "SELECT actor_id, granted_by_actor_id FROM actor_org_roles "
        "WHERE org_id = %s ORDER BY actor_id",
        (ids["org"],),
    ).fetchall() == [(ids["human"], None)]
    assert get_invite(universe, ids["invite"]).invited_by_actor_id is None
    assert _source_default(universe) == entry.ITEM_SOURCE_DEFAULT
    entry.apply(universe)
    universe.commit()
    entry.invariants(universe)


def test_unexpected_required_reference_refuses_before_any_change(universe) -> None:
    ids = _older_universe(universe)
    mint_token(universe, actor_id=ids["core"], name="stray")
    with pytest.raises(RuntimeError, match="core_actor_reference_unexpected: api_tokens.actor_id"):
        entry.apply(universe)
    universe.rollback()
    assert entry._core_actor_id(universe) == ids["core"]
    assert not _nullable(universe, "session_messages", "sender_actor_id")
    with pytest.raises(RuntimeError, match="core_actor_present"):
        entry.invariants(universe)
