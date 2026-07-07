"""Tests for actor and path-claim DDL — fresh-install shape and constraints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.schema_common import _get_columns, _get_indexes, _table_exists
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
    required_tables,
)
from yoke_core.domain.schema_init_path_tables import (
    create_path_registry_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_actor_path_claim_schema() -> None:
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    c = db_backend.connect()
    try:
        create_core_tables(c)
        seed_project_identities(c)
        ensure_event_schema(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        c.commit()
    finally:
        c.close()


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    with init_test_db(tmp_path, apply_schema=_apply_actor_path_claim_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _integrity_error_types(conn: Any) -> tuple[type[Exception], ...]:
    return db_backend.integrity_error_types(conn)


def _p(conn: Any) -> str:
    return "%s"


def _insert_actor(conn: Any, kind: str, component: str | None = None) -> int:
    p = _p(conn)
    return conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        f"VALUES ({p}, {p}, {p}) RETURNING id",
        (kind, component, _now()),
    ).fetchone()[0]


def _insert_human_actor(conn: Any) -> int:
    return _insert_actor(conn, "human")


def test_all_five_tables_exist(conn):
    names = sorted(table for table in required_tables() if _table_exists(conn, table))
    assert names == sorted(required_tables())


def test_create_is_idempotent(conn):
    # Calling again must not raise and must not duplicate rows or tables.
    create_actor_path_claim_tables(conn)
    create_actor_path_claim_tables(conn)
    assert _table_exists(conn, "actors")


def test_actor_kind_check_rejects_unknown(conn):
    with pytest.raises(_integrity_error_types(conn)):
        _insert_actor(conn, "alien")


def test_system_actor_requires_component(conn):
    with pytest.raises(_integrity_error_types(conn)):
        _insert_actor(conn, "system")


def test_human_actor_rejects_component(conn):
    with pytest.raises(_integrity_error_types(conn)):
        _insert_actor(conn, "human", "anything")


def test_system_component_unique_when_present(conn):
    _insert_actor(conn, "system", "yoke-core")
    with pytest.raises(_integrity_error_types(conn)):
        _insert_actor(conn, "system", "yoke-core")


def test_human_actors_can_share_null_component(conn):
    _insert_human_actor(conn)
    _insert_human_actor(conn)
    rows = conn.execute(
        "SELECT COUNT(*) FROM actors WHERE kind='human'"
    ).fetchone()
    assert rows[0] == 2


def test_actor_labels_unique_label_per_surface(conn):
    p = _p(conn)
    aid = _insert_actor(conn, "system", "yoke-core")
    bid = _insert_human_actor(conn)
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        f"VALUES ({p}, 'github_label', 'yoke-core', {p})",
        (aid, _now()),
    )
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
            f"VALUES ({p}, 'github_label', 'yoke-core', {p})",
            (bid, _now()),
        )


def test_actor_labels_unique_actor_per_surface(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        f"VALUES ({p}, 'github_label', 'ben', {p})",
        (aid, _now()),
    )
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
            f"VALUES ({p}, 'github_label', 'ben-alt', {p})",
            (aid, _now()),
        )


def test_path_claim_state_check(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, integration_target, registered_at) "
            f"VALUES ('ghost', 'exclusive', {p}, 'main', {p})",
            (aid, _now()),
        )


def test_path_claim_mode_check_blocks_unknown_mode(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, integration_target, registered_at) "
            f"VALUES ('planned', 'speculative', {p}, 'main', {p})",
            (aid, _now()),
        )


def test_path_claim_targets_unique_per_claim(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    cid = conn.execute(
        "INSERT INTO path_claims (actor_id, integration_target, registered_at) "
        f"VALUES ({p}, 'main', {p}) RETURNING id",
        (aid, _now()),
    ).fetchone()[0]
    tid = conn.execute(
        "INSERT INTO path_targets (project_id, kind, path_string, generation, created_at) "
        f"VALUES (1, 'file', 'runtime/foo.py', 1, {p}) RETURNING id",
        (_now(),),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        f"VALUES ({p}, {p}, {p})",
        (cid, tid, _now()),
    )
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            f"VALUES ({p}, {p}, {p})",
            (cid, tid, _now()),
        )


def test_path_claims_typed_owner_columns_exist(conn):
    cols = set(_get_columns(conn, "path_claims"))
    assert {
        "owner_kind",
        "owner_item_id",
        "owner_session_id",
        "owner_work_claim_id",
        "registered_by_actor_id",
        "registered_by_session_id",
    }.issubset(cols)


def test_path_claims_owner_kind_check_rejects_unknown(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    with pytest.raises(_integrity_error_types(conn)):
        conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, "
            "integration_target, registered_at, owner_kind) "
            f"VALUES ('planned', 'exclusive', {p}, 'main', {p}, 'rogue')",
            (aid, _now()),
        )


def test_path_claims_owner_kind_accepts_null_during_cutover(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    conn.execute(
        "INSERT INTO path_claims (state, mode, actor_id, "
        "integration_target, registered_at) "
        f"VALUES ('planned', 'exclusive', {p}, 'main', {p})",
        (aid, _now()),
    )


def test_path_claims_typed_owner_indexes_exist(conn):
    indexes = set(_get_indexes(conn, "path_claims"))
    assert "idx_path_claims_owner_kind" in indexes
    assert "idx_path_claims_owner_item" in indexes
    assert "idx_path_claims_owner_session" in indexes
    assert "idx_path_claims_owner_work_claim" in indexes


def test_path_claim_amendment_default_payload(conn):
    p = _p(conn)
    aid = _insert_human_actor(conn)
    cid = conn.execute(
        "INSERT INTO path_claims (actor_id, integration_target, registered_at) "
        f"VALUES ({p}, 'main', {p}) RETURNING id",
        (aid, _now()),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO path_claim_amendments (claim_id, amended_at, amendment_kind) "
        f"VALUES ({p}, {p}, 'scope_widen')",
        (cid, _now()),
    )
    payload = conn.execute(
        f"SELECT payload FROM path_claim_amendments WHERE claim_id={p}",
        (cid,),
    ).fetchone()[0]
    assert payload == "{}"
