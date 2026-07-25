"""Schema-init coverage for UI preferences and activation-fact tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_init import converge_core_schema
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.schema_readiness import READINESS_TABLES
from yoke_core.domain.ui_preferences_schema import (
    REQUIRED_UI_PREFERENCE_TABLES,
    create_ui_preference_tables,
)


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_actor_identity_tables(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_fresh_create_then_rerun_is_idempotent(conn):
    create_ui_preference_tables(conn)
    for table in REQUIRED_UI_PREFERENCE_TABLES:
        assert _table_exists(conn, table), f"missing table {table}"

    # Re-run against the already-initialized DB: no error, same shape.
    create_ui_preference_tables(conn)
    for table in REQUIRED_UI_PREFERENCE_TABLES:
        assert _table_exists(conn, table)


def test_preference_rows_are_unique_per_actor_and_key(conn):
    create_ui_preference_tables(conn)
    actor_id = seed_human_actor(conn)
    conn.execute(
        "INSERT INTO actor_ui_preferences (actor_id, pref_key, value, updated_at) "
        "VALUES (%s, 'overview.module.dismissed.first_deploy', '1', "
        "'2026-01-01T00:00:00Z')",
        (actor_id,),
    )
    conn.commit()
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO actor_ui_preferences (actor_id, pref_key, value, updated_at) "
            "VALUES (%s, 'overview.module.dismissed.first_deploy', '1', "
            "'2026-01-02T00:00:00Z')",
            (actor_id,),
        )
    conn.rollback()
    # The upsert shape the dismissal write uses relies on that constraint.
    conn.execute(
        "INSERT INTO actor_ui_preferences (actor_id, pref_key, value, updated_at) "
        "VALUES (%s, 'overview.module.dismissed.first_deploy', '1', "
        "'2026-01-03T00:00:00Z') "
        "ON CONFLICT (actor_id, pref_key) DO UPDATE SET "
        "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
        (actor_id,),
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM actor_ui_preferences").fetchone()[0]
    assert int(count) == 1


def test_activation_facts_are_unique_per_module_key(conn):
    create_ui_preference_tables(conn)
    conn.execute(
        "INSERT INTO overview_activation_facts (module_key, activated_at) "
        "VALUES ('connect_harness', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    # The monotone latch inserts with conflict-skip, never a second row.
    conn.execute(
        "INSERT INTO overview_activation_facts (module_key, activated_at) "
        "VALUES ('connect_harness', '2026-02-02T00:00:00Z') "
        "ON CONFLICT (module_key) DO NOTHING"
    )
    conn.commit()
    row = conn.execute(
        "SELECT activated_at FROM overview_activation_facts "
        "WHERE module_key = 'connect_harness'"
    ).fetchone()
    assert row[0] == "2026-01-01T00:00:00Z"


def test_boot_converge_propagates_tables_to_a_pre_existing_universe(
    tmp_path: Path,
) -> None:
    """A universe born before these tables gains them on boot converge."""
    with init_test_db(tmp_path) as db_path:
        c = connect_test_db(db_path)
        try:
            for table in REQUIRED_UI_PREFERENCE_TABLES:
                c.execute(f"DROP TABLE IF EXISTS {table}")
            c.commit()
            for table in REQUIRED_UI_PREFERENCE_TABLES:
                assert _table_exists(c, table) is False

            converge_core_schema(c)

            for table in REQUIRED_UI_PREFERENCE_TABLES:
                assert _table_exists(c, table) is True
        finally:
            c.close()


def test_readiness_probe_expects_a_ui_preference_table():
    assert "actor_ui_preferences" in READINESS_TABLES
