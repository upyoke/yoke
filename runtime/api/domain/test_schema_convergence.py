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
from yoke_core.domain.schema_fingerprint import fingerprint_kind
from yoke_core.domain.schema_init import converge_core_schema
from yoke_core.domain.schema_init_columns import apply_idempotent_migrations

# Recent additive tables a universe born before them would be missing — the
# exact drift observed on the live control plane before this fix.
_RECENT_ADDITIVE_TABLES = (
    "actor_external_identities",
    "actor_invites",
    "web_sessions",
    "github_app_installations",
    "project_github_repo_bindings",
)


def _regress_to_pre_additive(conn) -> None:
    """Drop recent additive schema from a fully-born universe to model a
    universe whose last full ``cmd_init`` predates it."""
    conn.execute("ALTER TABLE projects DROP COLUMN IF EXISTS github_sync_mode")
    conn.execute("ALTER TABLE projects DROP COLUMN IF EXISTS breakage_policy")
    for name in ("resolution", "resolution_ref", "resolution_comment"):
        conn.execute(f"ALTER TABLE items DROP COLUMN IF EXISTS {name}")
    conn.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS auto_join_domain")
    for tbl in reversed(_RECENT_ADDITIVE_TABLES):
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
            assert _column_exists(conn, "projects", "breakage_policy") is False
            assert _column_exists(conn, "items", "resolution") is False
            assert _table_exists(conn, "actor_external_identities") is False
            assert _table_exists(conn, "github_app_installations") is False
            assert _table_exists(conn, "project_github_repo_bindings") is False

            converge_core_schema(conn)

            assert _column_exists(conn, "projects", "github_sync_mode") is True
            assert _column_exists(conn, "projects", "breakage_policy") is True
            for name in ("resolution", "resolution_ref", "resolution_comment"):
                assert _column_exists(conn, "items", name) is True
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


def test_converge_adds_flow_status_and_missing_builtin_definitions(
    tmp_path: Path,
) -> None:
    """A release boot makes new flow configuration usable without DB repair."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "DELETE FROM deployment_flows "
                "WHERE id = 'yoke-hosted-production'"
            )
            conn.execute("ALTER TABLE deployment_flows DROP COLUMN status")
            conn.commit()

            converge_core_schema(conn)

            assert _column_exists(conn, "deployment_flows", "status") is True
            row = conn.execute(
                "SELECT df.status, p.slug AS project "
                "FROM deployment_flows df "
                "JOIN projects p ON p.id = df.project_id "
                "WHERE df.id = 'yoke-hosted-production'"
            ).fetchone()
            assert row == {"status": "active", "project": "yoke"}
        finally:
            conn.close()


def test_converge_preserves_disabled_flow_and_historical_run(
    tmp_path: Path,
) -> None:
    """Catalog convergence never re-enables definitions or purges run history."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "UPDATE deployment_flows SET status = 'disabled' "
                "WHERE id = 'yoke-internal'"
            )
            conn.execute(
                "INSERT INTO deployment_runs "
                "(id, project, flow, target_env, status, current_stage, "
                "created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "run-20260716-999",
                    "yoke",
                    "yoke-internal",
                    "production",
                    "completed",
                    "complete",
                    "operator",
                    "2026-07-16T00:00:00Z",
                ),
            )
            conn.commit()

            converge_core_schema(conn)

            status = conn.execute(
                "SELECT status FROM deployment_flows "
                "WHERE id = 'yoke-internal'"
            ).fetchone()[0]
            run_count = conn.execute(
                "SELECT COUNT(*) FROM deployment_runs "
                "WHERE id = 'run-20260716-999'"
            ).fetchone()[0]
            assert status == "disabled"
            assert int(run_count) == 1
        finally:
            conn.close()


def test_converge_restores_github_repository_identity_index(
    tmp_path: Path,
) -> None:
    """Boot convergence restores immutable repository-identity uniqueness."""
    index_name = "uq_project_github_repo_bindings_installation_repository_id"
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            conn.commit()

            converge_core_schema(conn)

            row = conn.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname=%s",
                (index_name,),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


def test_converge_adds_verified_github_api_origin_columns(
    tmp_path: Path,
) -> None:
    """Existing App-binding tables gain the origin needed for safe auth."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute("ALTER TABLE project_github_repo_bindings DROP COLUMN api_url")
            conn.execute("ALTER TABLE github_app_installations DROP COLUMN api_url")
            conn.commit()

            converge_core_schema(conn)

            assert _column_exists(conn, "github_app_installations", "api_url")
            assert _column_exists(conn, "project_github_repo_bindings", "api_url")
        finally:
            conn.close()


def test_converge_adds_project_github_sync_receipt_columns(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            for name in ("last_sync_at", "last_sync_outcome", "last_sync_error"):
                conn.execute(f"ALTER TABLE project_github_repo_bindings DROP COLUMN {name}")
            conn.commit()

            converge_core_schema(conn)

            for name in ("last_sync_at", "last_sync_outcome", "last_sync_error"):
                assert _column_exists(conn, "project_github_repo_bindings", name)
        finally:
            conn.close()


def test_fresh_and_upgraded_github_binding_schemas_have_one_fingerprint(
    tmp_path: Path,
) -> None:
    """Fresh birth must preserve the column order produced by additive boot.

    Portable restore creates a fresh trusted schema, while hosted targets are
    commonly upgraded in place.  Their exact fingerprints must agree.
    """
    with init_test_db(tmp_path / "fresh") as db_path:
        conn = connect_test_db(db_path)
        try:
            fresh_fingerprint = fingerprint_kind("postgres", conn)
        finally:
            conn.close()

    with init_test_db(tmp_path / "upgraded") as db_path:
        conn = connect_test_db(db_path)
        try:
            for name in ("last_sync_at", "last_sync_outcome", "last_sync_error"):
                conn.execute(
                    f"ALTER TABLE project_github_repo_bindings DROP COLUMN {name}"
                )
            conn.commit()

            converge_core_schema(conn)

            upgraded_fingerprint = fingerprint_kind("postgres", conn)
        finally:
            conn.close()

    assert upgraded_fingerprint == fresh_fingerprint


def test_converged_github_app_schema_accepts_id_free_postgres_inserts(
    tmp_path: Path,
) -> None:
    """Natural keys keep App binding writes portable to native Postgres."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _regress_to_pre_additive(conn)
            converge_core_schema(conn)
            now = "2026-07-09T12:00:00Z"
            conn.execute(
                "INSERT INTO github_app_installations "
                "(installation_id, account_id, account_login, account_type, "
                "permissions, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("12345", "9988", "example-org", "Organization", "{}", now, now),
            )
            conn.execute(
                "INSERT INTO project_github_repo_bindings "
                "(project_id, installation_id, repository_id, github_repo, "
                "permissions, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (1, "12345", "4567", "example-org/yoke", "{}", now, now),
            )
            conn.commit()

            row = conn.execute(
                "SELECT project_id, installation_id, repository_id "
                "FROM project_github_repo_bindings WHERE project_id=%s",
                (1,),
            ).fetchone()
            assert row == {
                "project_id": 1,
                "installation_id": "12345",
                "repository_id": "4567",
            }
        finally:
            conn.close()
