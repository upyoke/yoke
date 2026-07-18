"""Secret handling and deploy-env resolution tests for ``yoke_core.domain.projects``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import projects
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.file_test_db import init_test_db


def _init_with_baseline_projects() -> None:
    """``cmd_init`` plus the two baseline test-project identity rows."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    projects.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


@pytest.fixture
def initialized_db(tmp_path: Path) -> str:
    with init_test_db(tmp_path, apply_schema=_init_with_baseline_projects) as db_path:
        yield db_path


# ---------------------------------------------------------------------------
# capability-set-secret / capability-get-secret / capability-list-secrets
# ---------------------------------------------------------------------------

class TestCapabilitySecrets:
    def test_set_and_get_literal_secret(self, initialized_db: str):
        msg = projects.cmd_capability_set_secret(
            "yoke", "deploy", "token", "deploy-secret",
            source="literal", db_path=initialized_db,
        )
        assert "token" in msg

        result = projects.cmd_capability_get_secret(
            "yoke", "deploy", "token", db_path=initialized_db,
        )
        assert result == "deploy-secret"

    def test_get_secret_rejects_file_source(self, monkeypatch):
        conn = _fake_secret_row(monkeypatch, "file")
        with pytest.raises(ValueError, match="unsupported source='file'"):
            projects.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn,
            )

    def test_get_secret_rejects_missing_file_source(self, monkeypatch):
        conn = _fake_secret_row(monkeypatch, "file")
        with pytest.raises(ValueError, match="unsupported source='file'"):
            projects.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn,
            )

    def test_get_secret_rejects_env_source(self, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_VAR", "env-secret-value")
        conn = _fake_secret_row(monkeypatch, "env")
        with pytest.raises(ValueError, match="unsupported source='env'"):
            projects.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn,
            )

    def test_get_secret_rejects_missing_env_source(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        conn = _fake_secret_row(monkeypatch, "env")
        with pytest.raises(ValueError, match="unsupported source='env'"):
            projects.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn,
            )

    def test_set_secret_external_source_raises(self, initialized_db: str):
        with pytest.raises(ValueError, match="source='literal'"):
            projects.cmd_capability_set_secret(
                "yoke", "deploy", "k", "v",
                source="file", db_path=initialized_db,
            )

    def test_get_secret_nonexistent_returns_none(self, initialized_db: str):
        result = projects.cmd_capability_get_secret(
            "yoke", "nonexistent-cap", "key", db_path=initialized_db,
        )
        assert result is None

    def test_list_secrets(self, initialized_db: str):
        projects.cmd_capability_set_secret(
            "yoke", "ssh", "key_a", "val_a", db_path=initialized_db,
        )
        projects.cmd_capability_set_secret(
            "yoke", "ssh", "key_b", "val_b", db_path=initialized_db,
        )
        output = projects.cmd_capability_list_secrets("yoke", "ssh", db_path=initialized_db)
        keys = output.strip().split("\n")
        assert "key_a" in keys
        assert "key_b" in keys

    def test_list_secrets_empty(self, initialized_db: str):
        output = projects.cmd_capability_list_secrets(
            "yoke", "nonexistent", db_path=initialized_db,
        )
        assert output == ""

    def test_upsert_secret_overwrites(self, initialized_db: str):
        projects.cmd_capability_set_secret(
            "yoke", "deploy", "tok", "old_val", db_path=initialized_db,
        )
        projects.cmd_capability_set_secret(
            "yoke", "deploy", "tok", "new_val", db_path=initialized_db,
        )
        result = projects.cmd_capability_get_secret(
            "yoke", "deploy", "tok", db_path=initialized_db,
        )
        assert result == "new_val"


def _fake_secret_row(monkeypatch, source: str):
    from yoke_core.domain import projects_capabilities as pc

    monkeypatch.setattr(pc, "resolve_project_id", lambda conn, project: 1)
    monkeypatch.setattr(
        pc,
        "query_one",
        lambda conn, sql, params: {"value": "external-ref", "source": source},
    )
    return object()


# ---------------------------------------------------------------------------
# resolve-deploy-envs
# ---------------------------------------------------------------------------

class TestResolveDeployEnvs:
    def test_resolves_from_environments_table(self, initialized_db: str):
        from yoke_core.domain.project_seed_test_helpers import (
            seed_externalwebapp_site_environments,
        )

        conn = connect(initialized_db)
        try:
            seed_externalwebapp_site_environments(conn)
        finally:
            conn.close()
        result = projects.cmd_resolve_deploy_envs("externalwebapp", db_path=initialized_db)
        assert result is not None
        envs = result.strip().split("\n")
        assert "production" in envs
        assert "staging" in envs

    def test_resolves_from_deployment_flows(self, initialized_db: str):
        conn = connect(initialized_db)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS deployment_flows ("
                "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, "
                "description TEXT, stages TEXT NOT NULL DEFAULT '[]', "
                "target_env TEXT, on_failure TEXT DEFAULT 'abort', "
                "created_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO deployment_flows "
                "(id, project_id, name, stages, target_env, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    "flow-test",
                    1,
                    "test-flow",
                    "[]",
                    "canary",
                    "2026-04-20T00:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        result = projects.cmd_resolve_deploy_envs("yoke", db_path=initialized_db)
        assert result is not None
        envs = result.strip().split("\n")
        assert "canary" in envs

    def test_resolves_from_capability_config(self, initialized_db: str):
        conn = connect(initialized_db)
        try:
            conn.execute(
                "INSERT INTO project_capabilities "
                "(project_id, type, settings, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT(project_id, type) DO NOTHING",
                (
                    1,
                    "deployment_environments",
                    json.dumps({"environments": ["alpha", "beta"]}),
                    "2026-04-20T00:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        conn = connect(initialized_db)
        try:
            # Yoke now carries seeded prod/stage environments, so clear ALL
            # of yoke's environments (not just the legacy local row) to drain
            # source 1 and exercise the deployment_environments capability
            # fallback.
            conn.execute(
                "DELETE FROM environments WHERE site IN "
                "(SELECT id FROM sites WHERE project_id=1)"
            )
            if _table_exists(conn, "deployment_flows"):
                conn.execute(
                    "DELETE FROM deployment_flows WHERE project_id=1"
                )
            conn.commit()
        finally:
            conn.close()

        result = projects.cmd_resolve_deploy_envs("yoke", db_path=initialized_db)
        assert result is not None
        envs = result.strip().split("\n")
        assert "alpha" in envs
        assert "beta" in envs

    def test_returns_none_when_no_envs(self, initialized_db: str):
        projects.cmd_create("empty", "Empty", db_path=initialized_db)
        result = projects.cmd_resolve_deploy_envs("empty", db_path=initialized_db)
        assert result is None
