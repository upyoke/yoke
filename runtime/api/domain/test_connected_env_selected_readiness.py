"""Exact-selection coverage for Postgres connected-env readiness."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain import connected_env_readiness_tunnel as tunnel
from yoke_core.domain import db_backend, machine_config, yoke_connected_env
from yoke_core.domain.connected_env_readiness import (
    SelectedPostgresError,
    activate_selected_postgres,
)
from yoke_core.domain.connected_env_readiness_connector import (
    ACTION_PROBE_OK,
    ACTION_RESTARTED,
    PROBE_CONFIRM_ATTEMPTS,
)


def _postgres_connection(dsn_file: Path, *, port: int, prod: bool) -> dict:
    return {
        "transport": "local-postgres",
        "prod": prod,
        "credential_source": {"kind": "dsn_file", "path": str(dsn_file)},
        "postgres": {
            "host": "127.0.0.1",
            "port": port,
            "tunnel": {
                "kind": "ssh",
                "bastion": "operator@bastion.example",
                "identity_file": "/keys/yoke-test.pem",
                "remote_host": "database.internal",
                "remote_port": 5432,
            },
        },
    }


@pytest.fixture
def selected_connections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    stage_dsn = tmp_path / "stage.dsn"
    prod_dsn = tmp_path / "prod.dsn"
    stage_dsn.write_text(
        "host=127.0.0.1 port=6547 user=stage password=stage-secret dbname=postgres",
        encoding="utf-8",
    )
    prod_dsn.write_text(
        "host=127.0.0.1 port=6548 user=prod password=prod-secret dbname=postgres",
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage",
                "connections": {
                    "stage": _postgres_connection(stage_dsn, port=6547, prod=False),
                    "prod": _postgres_connection(prod_dsn, port=6548, prod=True),
                    "hosted": {
                        "transport": "https",
                        "api_url": "https://api.example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    },
                },
                "projects": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))
    # Replacing a forward takes machine-wide coordination state; keep it in
    # tmp_path rather than the operator's own machine home.
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv("YOKE_ENV", "preexisting-control-plane")
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV,
        "host=ambient.example user=wrong password=ambient-secret dbname=wrong",
    )
    return {"stage": stage_dsn.read_text(), "prod": prod_dsn.read_text()}


@pytest.mark.parametrize("environment", ["stage", "prod"])
def test_exact_label_uses_declared_dsn_and_restores_ambient_selection(
    selected_connections: dict,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    probes: list[str] = []
    monkeypatch.setattr(tunnel, "_probe_failure", lambda dsn: probes.append(dsn))
    monkeypatch.setattr(
        tunnel,
        "_replace_forward",
        lambda _spec, _dsn: pytest.fail("a live tunnel must not be replaced"),
    )

    authority = activate_selected_postgres(environment)

    assert authority.environment == environment
    assert authority.dsn == selected_connections[environment]
    assert authority.readiness.action == ACTION_PROBE_OK
    assert probes == [selected_connections[environment]]
    assert os.environ["YOKE_ENV"] == "preexisting-control-plane"
    assert db_backend.resolve_pg_dsn().startswith("host=ambient.example")
    assert "secret" not in repr(authority)


def test_dead_selected_tunnel_is_restarted(
    selected_connections: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = iter(["down"] * (1 + PROBE_CONFIRM_ATTEMPTS) + [None])
    restarts: list[object] = []

    def replace(spec: object, _dsn: str) -> str:
        restarts.append(spec)
        return ACTION_RESTARTED

    monkeypatch.setattr(tunnel, "_probe_failure", lambda _dsn: next(outcomes))
    monkeypatch.setattr(tunnel, "_replace_forward", replace)
    monkeypatch.setattr(tunnel.time, "sleep", lambda _delay: None)

    authority = activate_selected_postgres("stage")

    assert authority.readiness.action == ACTION_RESTARTED
    assert len(restarts) == 1


def test_https_and_unknown_selections_fail_without_ambient_fallback(
    selected_connections: dict,
) -> None:
    with pytest.raises(SelectedPostgresError, match="requires local-postgres"):
        activate_selected_postgres("hosted")
    with pytest.raises(SelectedPostgresError, match="missing"):
        activate_selected_postgres("missing")
    assert os.environ["YOKE_ENV"] == "preexisting-control-plane"
