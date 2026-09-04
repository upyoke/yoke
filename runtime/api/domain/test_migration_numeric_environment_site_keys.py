"""Numeric site/environment key migration coverage."""

from __future__ import annotations

import importlib
import json
import sqlite3

from yoke_core.domain import flow_init
from yoke_core.domain.migrations import (
    _numeric_environment_site_json as json_helpers,
)
from yoke_core.domain.migrations import (
    _numeric_environment_site_keys as key_helpers,
)


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0010_numeric_environment_site_keys"
)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, name TEXT);
        INSERT INTO projects VALUES (1, 'yoke', 'Yoke');
        CREATE TABLE sites (
            id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,
            description TEXT, created_at TEXT NOT NULL, settings TEXT DEFAULT '{}'
        );
        CREATE TABLE environments (
            id TEXT PRIMARY KEY, site TEXT NOT NULL, name TEXT NOT NULL,
            url TEXT, deploy_method TEXT, deploy_command TEXT,
            health_check_url TEXT, config_notes TEXT, last_deployed_at TEXT,
            created_at TEXT NOT NULL, settings TEXT DEFAULT '{}',
            UNIQUE(site, name)
        );
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY, project_id INTEGER, target_tier TEXT,
            target_environment_id TEXT REFERENCES environments(id),
            CHECK ((target_tier = 'persistent') =
                   (target_environment_id IS NOT NULL))
        );
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY, project_id INTEGER, target_tier TEXT,
            target_environment_id TEXT REFERENCES environments(id),
            CHECK ((target_tier = 'persistent') =
                   (target_environment_id IS NOT NULL))
        );
        CREATE TABLE qa_plans (
            id INTEGER PRIMARY KEY, project_id INTEGER,
            target_environment_id TEXT REFERENCES environments(id)
        );
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY, project_id INTEGER, type TEXT, settings TEXT
        );
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY, method_config TEXT,
            execution_target_json TEXT, execution_target_digest TEXT
        );
        CREATE TABLE events (id INTEGER PRIMARY KEY, envelope TEXT);
        INSERT INTO sites VALUES (
            'yoke-api', 1, 'Yoke API', NULL, '2026-01-01', '{}'
        );
        INSERT INTO environments VALUES (
            'production', 'yoke-api', 'prod', NULL, NULL, NULL, NULL, NULL,
            NULL, '2026-01-01', '{}'
        );
        INSERT INTO environments VALUES (
            'stage', 'yoke-api', 'stage', NULL, NULL, NULL, NULL, NULL,
            NULL, '2026-01-01', '{}'
        );
        INSERT INTO deployment_flows VALUES (
            'release', 1, 'persistent', 'production'
        );
        INSERT INTO deployment_runs VALUES (
            'run-1', 1, 'persistent', 'production'
        );
        INSERT INTO qa_plans VALUES (1, 1, 'stage');
        """
    )
    capability = {
        "environment_by_target": {"prod": "production", "stage": "stage"},
        "migration_receipts": {"yoke-api": {"stack_names": ["core"]}},
    }
    conn.execute(
        "INSERT INTO project_capabilities VALUES (1,1,'release_pin',?)",
        (json.dumps(capability),),
    )
    target = {
        "schema": 1,
        "site": {"id": "yoke-api"},
        "environment": {"id": "production", "name": "prod"},
    }
    conn.execute(
        "INSERT INTO qa_requirements VALUES (1,?,?,?)",
        (
            json.dumps({"target_environment_id": "production"}),
            json.dumps(target),
            "old-digest",
        ),
    )
    conn.execute(
        "INSERT INTO events VALUES (1,?)",
        (json.dumps({"environment_id": "production"}),),
    )
    return conn


def test_migration_rewrites_keys_references_and_stored_payloads(monkeypatch) -> None:
    conn = _database()
    monkeypatch.setattr(
        flow_init,
        "create_or_replace_item_progress_view",
        lambda *_a, **_k: None,
    )

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert {
        row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(sites)")
    }["id"] == "INTEGER"
    assert {
        row["name"]: row["type"]
        for row in conn.execute("PRAGMA table_info(environments)")
    }["id"] == "INTEGER"
    environments = {
        row["name"]: row["id"]
        for row in conn.execute("SELECT id,name FROM environments")
    }
    assert (
        conn.execute("SELECT target_environment_id FROM deployment_runs").fetchone()[0]
        == environments["prod"]
    )
    assert (
        conn.execute("SELECT target_environment_id FROM qa_plans").fetchone()[0]
        == environments["stage"]
    )

    settings = json.loads(
        conn.execute("SELECT settings FROM project_capabilities").fetchone()[0]
    )
    assert "environment_by_target" not in settings
    assert "Yoke API" in settings["migration_receipts"]
    requirement = conn.execute(
        "SELECT method_config,execution_target_json,execution_target_digest "
        "FROM qa_requirements"
    ).fetchone()
    assert json.loads(requirement["method_config"]) == {"target_environment": "prod"}
    assert json.loads(requirement["execution_target_json"])["site"] == {
        "name": "Yoke API"
    }
    assert requirement["execution_target_digest"] != "old-digest"
    assert json.loads(conn.execute("SELECT envelope FROM events").fetchone()[0]) == {
        "environment": "prod"
    }

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)


def test_migration_declares_a_serving_floor() -> None:
    assert MIGRATION.MINIMUM_SERVING_VERSION == "0.1.1+launch.234"


def test_postgres_target_constraint_discovery_escapes_like_pattern(
    test_db,
) -> None:
    key_helpers._drop_target_constraints(test_db)
    assert (
        test_db.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid=to_regclass(%s) AND conname=%s",
            ("deployment_flows", "deployment_flows_target_tier_vocabulary"),
        ).fetchone()
        is None
    )


def test_stored_reference_recode_prefers_the_resolved_row_reference() -> None:
    for payload in (
        {"environment": "production", "environment_id": "yoke-api-prod"},
        {"environment_id": "yoke-api-prod", "environment": "production"},
    ):
        assert json_helpers._recode_value(payload, {"yoke-api-prod": "prod"}, {}) == {
            "environment": "prod"
        }
