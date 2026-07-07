"""Setup-error teaching for local-postgres-only operations selected under a
non-local (https) env: the error names why, enumerates the machine's
configured local-postgres envs, and teaches the ``YOKE_ENV=<env>``
override recipe instead of the raw DSN setup error.

Kept separate from ``test_yoke_connected_env`` (near the authored-line cap).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend, machine_config, yoke_connected_env
from yoke_contracts.machine_config import schema as contract


def _https_active_binding(tmp_path: Path, *, with_local_env: bool = True) -> Path:
    token_file = tmp_path / "prod.token"
    token_file.write_text("tok\n", encoding="utf-8")
    dsn_file = tmp_path / "cloud.dsn"
    dsn_file.write_text("host=127.0.0.1 port=6547 dbname=x\n", encoding="utf-8")
    connections: dict = {
        "prod": {
            "transport": "https",
            "api_url": "https://api.example.test",
            "credential_source": {"kind": "token_file", "path": str(token_file)},
        },
    }
    if with_local_env:
        connections["prod-db-admin"] = {
            "transport": "local-postgres",
            "credential_source": {"kind": "dsn_file", "path": str(dsn_file)},
            "postgres": {"host": "127.0.0.1", "port": 6547},
        }
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "active_env": "prod",
        "connections": connections,
        "projects": {str(tmp_path.resolve()): {"project_id": 1}},
    }), encoding="utf-8")
    return path


@pytest.fixture
def https_active(tmp_path, monkeypatch):
    for key in (db_backend.PG_DSN_ENV, db_backend.PG_DSN_FILE_ENV, "YOKE_ENV"):
        monkeypatch.delenv(key, raising=False)
    binding = _https_active_binding(tmp_path)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    return binding


def test_resolve_postgres_dsn_teaches_env_override(https_active, monkeypatch):
    # Pin the invocation seam: under pytest the live __main__ spec would
    # reconstruct the test runner's argv, not an operator command. The
    # pinned example is a genuinely local-postgres-only surface (direct
    # SQL); wrapped `yoke` commands relay over https instead.
    monkeypatch.setattr(
        contract, "_invocation_recipe",
        lambda *a, **k: 'python3 -m yoke_core.cli.db_router query "SELECT 1"',
    )

    with pytest.raises(yoke_connected_env.ConnectedEnvNotLocalPostgres) as e:
        yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )

    msg = str(e.value)
    assert "'prod'" in msg and "https" in msg
    assert "requires a local-postgres env" in msg
    assert "YOKE_ENV=prod-db-admin" in msg
    assert "configured local-postgres envs: prod-db-admin" in msg
    assert "--env prod-db-admin" in msg


def test_resolve_postgres_dsn_without_local_env_teaches_config(
    tmp_path, monkeypatch,
):
    for key in (db_backend.PG_DSN_ENV, db_backend.PG_DSN_FILE_ENV, "YOKE_ENV"):
        monkeypatch.delenv(key, raising=False)
    binding = _https_active_binding(tmp_path, with_local_env=False)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")

    with pytest.raises(yoke_connected_env.ConnectedEnvNotLocalPostgres) as e:
        yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )

    msg = str(e.value)
    assert "No local-postgres env is configured" in msg
    assert "yoke config example" in msg


def test_db_backend_surfaces_teaching_without_dsn_setup_framing(
    https_active, monkeypatch,
):
    """resolve_pg_dsn must NOT bury the recipe under the generic
    'YOKE_PG_DSN ... must be set for postgres authority' wrapper."""
    recipe = 'python3 -m yoke_core.cli.db_router query "SELECT 1"'
    monkeypatch.setattr(contract, "_invocation_recipe",
                        lambda *a, **k: recipe)

    with pytest.raises(RuntimeError) as e:
        db_backend.resolve_pg_dsn()

    msg = str(e.value)
    assert "must be set for postgres authority" not in msg
    assert f"YOKE_ENV=prod-db-admin {recipe}" in msg


def test_yoke_env_override_resolves_local_env(https_active, monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")

    resolved = yoke_connected_env.resolve_postgres_dsn(
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    )

    assert resolved.dsn.startswith("host=127.0.0.1")
    assert resolved.evidence["environment"] == "prod-db-admin"
