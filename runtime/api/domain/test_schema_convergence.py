"""Tests for boot-time schema convergence.

A prod/self-host deploy only reconciles schema on the boot after core-deploy,
and that boot runs :func:`yoke_core.domain.schema_init.converge_core_schema`
(via :func:`yoke_core.api.server_entrypoint.ensure_core_schema`). These tests
prove a universe born before a recent additive change converges to the current
schema on boot — WITHOUT running the birth-only destructive drops or data
backfills that :func:`apply_legacy_data_migrations` carries.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init import converge_core_schema
from yoke_core.domain.schema_init_columns import apply_idempotent_migrations

# Recent additive tables a universe born before them would be missing — the
# exact drift observed on the live control plane before this fix.
_RECENT_ADDITIVE_TABLES = ("actor_external_identities", "actor_invites", "web_sessions")


def _regress_to_pre_additive(conn) -> None:
    """Drop recent additive schema from a fully-born universe to model a
    universe whose last full ``cmd_init`` predates it."""
    conn.execute("ALTER TABLE projects DROP COLUMN IF EXISTS github_sync_mode")
    conn.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS auto_join_domain")
    for tbl in _RECENT_ADDITIVE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.commit()


def _row_count(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    if row is None:
        return 0
    return row["n"] if isinstance(row, dict) else row[0]


def test_converge_adds_missing_columns_and_tables(tmp_path: Path) -> None:
    """Boot converge restores additive columns AND tables added after birth —
    the propagation gap that stranded ``projects.github_sync_mode`` on prod."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _regress_to_pre_additive(conn)
            assert _column_exists(conn, "projects", "github_sync_mode") is False
            assert _table_exists(conn, "actor_external_identities") is False

            converge_core_schema(conn)

            assert _column_exists(conn, "projects", "github_sync_mode") is True
            assert _column_exists(conn, "organizations", "auto_join_domain") is True
            for tbl in _RECENT_ADDITIVE_TABLES:
                assert _table_exists(conn, tbl) is True
        finally:
            conn.close()


def test_converge_is_non_destructive(tmp_path: Path) -> None:
    """Converge must NOT run the birth-only drops: a retired surface the full
    init chain would drop survives the boot converge untouched."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            # epic_reviews is dropped by apply_legacy_data_migrations at full
            # init; converge must never touch it.
            conn.execute("CREATE TABLE epic_reviews (id INTEGER)")
            conn.execute("INSERT INTO epic_reviews (id) VALUES (1)")
            conn.commit()

            converge_core_schema(conn)

            assert _table_exists(conn, "epic_reviews") is True
            assert _row_count(conn, "epic_reviews") == 1
        finally:
            conn.close()


def test_full_migration_wrapper_still_drops_legacy(tmp_path: Path) -> None:
    """The birth/full-init path (apply_idempotent_migrations) keeps running the
    destructive tail — the split routed the drop to the birth-only path, it did
    not delete it."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute("CREATE TABLE epic_reviews (id INTEGER)")
            conn.commit()
            assert _table_exists(conn, "epic_reviews") is True

            apply_idempotent_migrations(conn)

            assert _table_exists(conn, "epic_reviews") is False
        finally:
            conn.close()


def test_converge_is_idempotent(tmp_path: Path) -> None:
    """Every boot runs converge; a second run against a converged universe must
    be a clean no-op, never an error."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            converge_core_schema(conn)
            converge_core_schema(conn)
            assert _column_exists(conn, "projects", "github_sync_mode") is True
        finally:
            conn.close()
