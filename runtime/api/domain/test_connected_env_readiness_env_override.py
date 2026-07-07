"""Readiness + self-heal for env-keyed local-postgres envs selected by
``YOKE_ENV`` while the machine-global ``active_env`` is https.

This is the post-flip dogfood shape: ``active_env=prod`` (https transport)
with ``YOKE_ENV=prod-db-admin`` routing one command at the tunnel-backed
local-postgres env. Kept separate from ``test_connected_env_readiness`` so
the main readiness test file remains under the authored-line cap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_readiness_tunnel as cer_t
from yoke_core.domain import machine_config
from yoke_core.domain import yoke_connected_env


@pytest.fixture(autouse=True)
def _reset_readiness_cache():
    cer.reset_cache()
    yield
    cer.reset_cache()


def _write_https_default_binding(tmp_path: Path) -> Path:
    """Machine config whose active env is https with a tunnel-backed
    local-postgres env beside it (the post-flip operator shape)."""
    dsn_file = tmp_path / "cloud.dsn"
    dsn_file.write_text("host=127.0.0.1 port=6547 user=u dbname=test_db\n",
                        encoding="utf-8")
    token_file = tmp_path / "prod.token"
    token_file.write_text("tok\n", encoding="utf-8")
    binding = {
        "schema_version": 1,
        "active_env": "prod",
        "connections": {
            "prod": {
                "transport": "https",
                "api_url": "https://api.example.test",
                "credential_source": {"kind": "token_file",
                                      "path": str(token_file)},
            },
            "prod-db-admin": {
                "transport": "local-postgres",
                "credential_source": {"kind": "dsn_file",
                                      "path": str(dsn_file)},
                "postgres": {
                    "host": "127.0.0.1",
                    "port": 6547,
                    "tunnel": {
                        "kind": "ssh",
                        "bastion": "ubuntu@10.0.0.1",
                        "identity_file": str(tmp_path / "key.pem"),
                        "remote_host": "aurora.example.internal",
                        "remote_port": 5432,
                    },
                },
            },
        },
        "projects": {str(tmp_path.resolve()): {"project_id": 1}},
    }
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding), encoding="utf-8")
    return path


@pytest.fixture
def https_default_env(tmp_path, monkeypatch):
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(cer_c.PG_DSN_FILE_ENV, raising=False)
    binding = _write_https_default_binding(tmp_path)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    return binding


def test_yoke_env_override_selects_managed_tunnel_connector(
        https_default_env, monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")

    detection = cer_c.detect()

    assert detection.connector_kind == cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG
    assert detection.environment == "prod-db-admin"
    assert detection.spec is not None
    assert detection.spec.forward_spec == "6547:aurora.example.internal:5432"


def test_yoke_env_override_self_heals_dead_tunnel(
        https_default_env, monkeypatch):
    results = iter([False, False, False, False, True])
    restarts: list = []
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setattr(cer_t, "_probe", lambda dsn: next(results))
    monkeypatch.setattr(cer_t, "_restart_tunnel",
                        lambda spec: restarts.append(spec))
    monkeypatch.setattr(cer_t.time, "sleep", lambda delay: None)

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.action == cer_c.ACTION_RESTARTED
    assert result.environment == "prod-db-admin"
    assert len(restarts) == 1
    assert restarts[0].bastion == "ubuntu@10.0.0.1"


def test_https_active_env_without_override_is_unmanaged(
        https_default_env, monkeypatch):
    monkeypatch.delenv("YOKE_ENV", raising=False)
    probes: list = []
    restarts: list = []
    monkeypatch.setattr(cer_t, "_probe", lambda dsn: probes.append(dsn) or True)
    monkeypatch.setattr(cer_t, "_restart_tunnel",
                        lambda spec: restarts.append(spec))

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.connector_kind == cer.CONNECTOR_UNMANAGED
    assert probes == [] and restarts == []


def test_refused_connect_under_override_is_a_tunnel_error(
        https_default_env, monkeypatch):
    """db_backend's reactive self-heal keys off this classifier; it must
    claim ownership when the override selects the managed tunnel env."""
    import psycopg

    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    refused = psycopg.OperationalError(
        'connection to server at "127.0.0.1", port 6547 failed: '
        "Connection refused"
    )

    assert cer.is_local_tunnel_connection_error(refused) is True

    monkeypatch.delenv("YOKE_ENV", raising=False)
    assert cer.is_local_tunnel_connection_error(refused) is False
