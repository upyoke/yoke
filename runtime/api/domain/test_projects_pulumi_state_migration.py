"""Pulumi operator-state migration and generic-boundary tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_get_settings,
    cmd_capability_merge_settings,
    cmd_capability_set_settings,
)
from yoke_core.domain.projects_pulumi_state_migration import (
    PulumiStateMigrationError,
    migrate_pulumi_state,
)


@pytest.fixture
def pulumi_state_db(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            project_id = resolve_project_id(conn, "yoke")
            conn.execute(
                "CREATE TABLE sites ("
                "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, created_at TEXT NOT NULL, "
                "settings TEXT DEFAULT '{}')"
            )
            conn.execute(
                "INSERT INTO sites "
                "(id, project_id, name, created_at, settings) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("main", project_id, "Main", "2026-01-01T00:00:00Z", "{}"),
            )
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def _seed_source(db_name: str, *, encrypted_key: str = "encrypted-material"):
    conn = pg_testdb.connect_test_database(db_name)
    try:
        settings = {
            "pulumi": {
                "other": "preserved",
                "stack_state": {
                    "yoke-infra": {
                        "secrets_provider": "awskms://alias/yoke-pulumi",
                        "encrypted_key": encrypted_key,
                    }
                },
            },
            "unrelated": True,
        }
        conn.execute(
            "UPDATE sites SET settings=%s WHERE id='main'",
            (json.dumps(settings),),
        )
        conn.commit()
    finally:
        conn.close()


def test_dry_run_rolls_back_then_apply_moves_and_converges(pulumi_state_db):
    _seed_source(pulumi_state_db)
    preview = migrate_pulumi_state(
        project="yoke", site_id="main", stack_names=["yoke-infra"]
    )
    assert preview["applied"] is False
    assert preview["mode"] == "migrate"
    assert "encrypted-material" not in json.dumps(preview)
    conn = pg_testdb.connect_test_database(pulumi_state_db)
    try:
        source = json.loads(
            conn.execute("SELECT settings FROM sites WHERE id='main'").fetchone()[0]
        )
        assert "stack_state" in source["pulumi"]
        assert conn.execute(
            "SELECT 1 FROM project_capabilities "
            "WHERE project_id=%s AND type='pulumi-state'",
            (resolve_project_id(conn, "yoke"),),
        ).fetchone() is None
    finally:
        conn.close()

    applied = migrate_pulumi_state(
        project="yoke",
        site_id="main",
        stack_names=["yoke-infra"],
        apply=True,
    )
    assert applied["applied"] is True
    assert applied["source_removed"] is True
    repeated = migrate_pulumi_state(
        project="yoke",
        site_id="main",
        stack_names=["yoke-infra"],
        apply=True,
    )
    assert repeated["mode"] == "already_applied"
    conn = pg_testdb.connect_test_database(pulumi_state_db)
    try:
        site = json.loads(
            conn.execute("SELECT settings FROM sites WHERE id='main'").fetchone()[0]
        )
        assert site == {"pulumi": {"other": "preserved"}, "unrelated": True}
        cap = json.loads(
            conn.execute(
                "SELECT settings FROM project_capabilities "
                "WHERE project_id=%s AND type='pulumi-state'",
                (resolve_project_id(conn, "yoke"),),
            ).fetchone()[0]
        )
        assert cap["stack_state"]["yoke-infra"]["encrypted_key"] == (
            "encrypted-material"
        )
    finally:
        conn.close()


def test_conflict_and_exact_set_refuse_without_writes(pulumi_state_db):
    _seed_source(pulumi_state_db)
    conn = pg_testdb.connect_test_database(pulumi_state_db)
    try:
        project_id = resolve_project_id(conn, "yoke")
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES (%s, %s, %s, %s)",
            (
                project_id,
                "pulumi-state",
                json.dumps({
                    "stack_state": {
                        "yoke-infra": {
                            "secrets_provider": "awskms://alias/yoke-pulumi",
                            "encrypted_key": "different",
                        }
                    }
                }),
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PulumiStateMigrationError) as raised:
        migrate_pulumi_state(
            project="yoke",
            site_id="main",
            stack_names=["yoke-infra"],
            apply=True,
        )
    assert raised.value.code == "stack_state_conflict"
    assert "different" not in str(raised.value)
    with pytest.raises(PulumiStateMigrationError) as mismatch:
        migrate_pulumi_state(
            project="yoke",
            site_id="main",
            stack_names=["yoke-infra", "yoke-vps"],
        )
    assert mismatch.value.code == "stack_set_mismatch"


def test_generic_surfaces_hide_stack_state_but_allow_top_level_merge(
    pulumi_state_db,
):
    _seed_source(pulumi_state_db)
    migrate_pulumi_state(
        project="yoke",
        site_id="main",
        stack_names=["yoke-infra"],
        apply=True,
    )
    with pytest.raises(ValueError, match="stack-scoped"):
        cmd_capability_get_settings("yoke", "pulumi-state")
    with pytest.raises(ValueError, match="full settings writes are closed"):
        cmd_capability_set_settings(
            "yoke", "pulumi-state", "{}", base_settings_json="{}"
        )
    with pytest.raises(ValueError, match="generic merge surface"):
        cmd_capability_merge_settings(
            "yoke", "pulumi-state", {"stack_state.yoke-infra.encrypted_key": "x"}
        )
    cmd_capability_merge_settings(
        "yoke", "pulumi-state", {"state_bucket": "yoke-state"}
    )
    conn = pg_testdb.connect_test_database(pulumi_state_db)
    try:
        stored = json.loads(
            conn.execute(
                "SELECT settings FROM project_capabilities "
                "WHERE project_id=%s AND type='pulumi-state'",
                (resolve_project_id(conn, "yoke"),),
            ).fetchone()[0]
        )
        assert stored["state_bucket"] == "yoke-state"
        assert "stack_state" in stored
    finally:
        conn.close()
