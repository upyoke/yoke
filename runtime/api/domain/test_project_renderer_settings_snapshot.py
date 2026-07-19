"""Tests for the renderer settings snapshot + stack-config payload."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from yoke_core.domain.project_renderer_settings_snapshot import (
    STACK_CONFIG_SCHEMA,
    ProjectNotFoundError,
    build_pulumi_stack_config,
    settings_from_snapshot,
    settings_from_stack_config,
    snapshot_from_settings,
)


def _sample_settings() -> ProjectRendererSettings:
    stage = RendererEnvironmentSettings(
        id="acme-api-stage",
        name="stage",
        settings={
            "hosts": {"api": "api.stage.acme.test", "origin": "o.stage.acme.test"},
            "pulumi": {
                "stack_name": "acme-stage",
                "origin_vps_stack_name": "acme-stage-vps",
                "secrets_provider": "awskms://alias/acme-pulumi-state",
                "encrypted_key": "ciphertext==",
            },
            "servers": [{"instance_type": "t4g.micro", "root_volume_gb": 40,
                         "aws_key_pair_name": "acme-stage"}],
            "database": {"name": "acme_stage", "master_username": "acme_admin",
                         "engine_version": "16.13", "min_capacity_acu": 0,
                         "max_capacity_acu": 4, "backup_retention_days": 7},
        },
    )
    return ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-api",
        site_settings={
            "domains": [{"domain_name": "acme.test", "hosted_zone_id": "ZACME"}],
        },
        primary_environment=stage,
        environments=(stage,),
        capabilities={
            "aws-admin": {"account_id": "123456789012", "region": "us-east-1"},
            "container-registry": {"repository": "acme"},
            "github": {"repo_owner": "acme-org", "repo_name": "acme"},
            "pulumi-state": {
                "kms_key_alias": "alias/acme-pulumi-state",
                "state_bucket": "acme-pulumi-state",
                "stacks": ["registry"],
            },
        },
    )


def _seeded_conn() -> Any:
    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(db_name), db_name,
    )
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
        "name TEXT, public_item_prefix TEXT DEFAULT 'YOK')"
    )
    conn.execute(
        "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER, "
        "name TEXT, settings TEXT)"
    )
    conn.execute(
        "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT, "
        "name TEXT, settings TEXT)"
    )
    conn.execute(
        "CREATE TABLE project_capabilities (project_id INTEGER, type TEXT, "
        "settings TEXT)"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
        (7, "acme", "Acme"),
    )
    conn.execute(
        "INSERT INTO sites (id, project_id, name, settings) "
        "VALUES (%s, %s, %s, %s)",
        ("acme-api", 7, "Acme API", json.dumps({
            "domains": [{"domain_name": "acme.test", "hosted_zone_id": "ZACME"}],
            "pulumi": {"stacks": ["registry"]},
        })),
    )
    conn.execute(
        "INSERT INTO environments (id, site, name, settings) "
        "VALUES (%s, %s, %s, %s)",
        ("acme-api-stage", "acme-api", "stage", json.dumps({
            "hosts": {"api": "api.stage.acme.test"},
            "pulumi": {"stack_name": "acme-stage",
                       "secrets_provider": "awskms://alias/acme-pulumi-state"},
        })),
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, %s, %s)",
        (7, "github", json.dumps({
            "repo_owner": "acme-org", "repo_name": "acme",
            "installation_id": "12345", "repository_id": "4567",
        })),
    )
    return conn


class TestSnapshotRoundTrip:
    def test_round_trip_preserves_settings(self):
        settings = _sample_settings()
        snapshot = snapshot_from_settings(settings)
        assert settings_from_snapshot(snapshot) == settings

    def test_snapshot_is_json_serializable(self):
        snapshot = snapshot_from_settings(_sample_settings())
        assert json.loads(json.dumps(snapshot)) == snapshot

    def test_missing_project_slug_raises(self):
        with pytest.raises(ValueError, match="project"):
            settings_from_snapshot({"environments": []})

    def test_non_list_environments_raises(self):
        with pytest.raises(ValueError, match="environments"):
            settings_from_snapshot({"project": "acme", "environments": {}})

    def test_unflagged_snapshot_keeps_first_environment_primary(self):
        settings = settings_from_snapshot({
            "project": "acme",
            "environments": [
                {"id": "acme-api-a-home", "name": "settings-home",
                 "settings": {}},
                {"id": "acme-api-live", "name": "live", "settings": {}},
            ],
        })
        assert settings.primary_environment is not None
        assert settings.primary_environment.id == "acme-api-a-home"

    def test_renderer_primary_flag_pins_hydrated_primary(self):
        settings = settings_from_snapshot({
            "project": "acme",
            "environments": [
                {"id": "acme-api-a-home", "name": "settings-home",
                 "settings": {}},
                {"id": "acme-api-live", "name": "live",
                 "settings": {"renderer_primary": True}},
            ],
        })
        assert settings.primary_environment is not None
        assert settings.primary_environment.id == "acme-api-live"


class TestBuildStackConfig:
    def test_envelope_shape_and_determinism(self):
        conn = _seeded_conn()
        try:
            first = build_pulumi_stack_config(conn, "acme")
            second = build_pulumi_stack_config(conn, "acme")
        finally:
            conn.close()
        assert first == second
        assert first["config_schema"] == STACK_CONFIG_SCHEMA
        assert first["project_id"] == 7
        assert first["project_slug"] == "acme"
        snapshot = first["renderer_settings"]
        assert snapshot["project"] == "acme"
        assert snapshot["site_settings"]["pulumi"]["stacks"] == ["registry"]
        assert snapshot["environments"][0]["id"] == "acme-api-stage"
        assert snapshot["capabilities"]["github"]["repo_name"] == "acme"

    def test_numeric_project_id_resolves(self):
        conn = _seeded_conn()
        try:
            payload = build_pulumi_stack_config(conn, "7")
        finally:
            conn.close()
        assert payload["project_slug"] == "acme"

    def test_unknown_project_raises(self):
        conn = _seeded_conn()
        try:
            with pytest.raises(ProjectNotFoundError):
                build_pulumi_stack_config(conn, "nope")
        finally:
            conn.close()


class TestSettingsFromStackConfig:
    def test_hydrates_from_envelope(self):
        settings = _sample_settings()
        payload = {
            "config_schema": STACK_CONFIG_SCHEMA,
            "project_id": 7,
            "project_slug": "acme",
            "renderer_settings": snapshot_from_settings(settings),
        }
        assert settings_from_stack_config(payload) == settings

    def test_unknown_schema_raises(self):
        with pytest.raises(ValueError, match="schema"):
            settings_from_stack_config({"config_schema": 99})

    def test_missing_snapshot_raises(self):
        with pytest.raises(ValueError, match="renderer_settings"):
            settings_from_stack_config({"config_schema": STACK_CONFIG_SCHEMA})
