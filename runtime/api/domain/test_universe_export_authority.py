"""Active-connection sanction contract for ``resolve_export_dsn``.

Export authority is DSN possession: a non-prod local-postgres
connection exports; https and prod-flagged Postgres refuse with
mode-specific guidance. Driven through a temp machine config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_core.domain import universe_export as ux
from yoke_core.domain import yoke_connected_env
from yoke_core.domain.json_helper import dumps_pretty


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv(machine_runtime.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.delenv(machine_runtime.CONFIG_FILE_ENV, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.delenv(yoke_connected_env.DISABLE_ENV, raising=False)


def _write_machine_config(machine_home: Path, payload: dict) -> None:
    machine_home.mkdir(parents=True, exist_ok=True)
    (machine_home / "config.json").write_text(
        dumps_pretty(payload),
        encoding="utf-8",
    )


def test_resolve_export_dsn_refuses_https_connection_in_mode_language(
    tmp_path,
):
    _write_machine_config(
        tmp_path / "machine-home",
        {
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "api_url": "https://api.example",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(tmp_path / "token"),
                    },
                },
            },
        },
    )

    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    message = str(excinfo.value)
    assert "DSN possession" in message
    assert "hosted" in message
    assert "Move universe" in message
    assert "self-host" in message
    assert "yoke init --local" in message


def test_resolve_export_dsn_refuses_prod_flagged_postgres(tmp_path):
    dsn_file = tmp_path / "prod.dsn"
    dsn_file.write_text("host=/prod-sock user=yoke dbname=yoke\n", encoding="utf-8")
    _write_machine_config(
        tmp_path / "machine-home",
        {
            "schema_version": 1,
            "active_env": "prod-db-admin",
            "connections": {
                "prod-db-admin": {
                    "transport": "local-postgres",
                    "prod": True,
                    "credential_source": {
                        "kind": "dsn_file",
                        "path": str(dsn_file),
                    },
                },
            },
        },
    )

    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    message = str(excinfo.value)
    assert "prod-flagged" in message
    assert "operator-only" in message


def test_resolve_export_dsn_returns_nonprod_local_postgres_dsn(tmp_path):
    dsn_file = tmp_path / "local.dsn"
    dsn_file.write_text("host=/sock user=yoke dbname=yoke\n", encoding="utf-8")
    _write_machine_config(
        tmp_path / "machine-home",
        {
            "schema_version": 1,
            "active_env": "local",
            "connections": {
                "local": {
                    "transport": "local-postgres",
                    "prod": False,
                    "credential_source": {
                        "kind": "dsn_file",
                        "path": str(dsn_file),
                    },
                },
            },
        },
    )

    assert ux.resolve_export_dsn() == "host=/sock user=yoke dbname=yoke"


def test_resolve_export_dsn_teaches_init_when_unconfigured(tmp_path):
    # No config.json under the isolated machine home: no binding at all.
    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    assert "yoke init --local" in str(excinfo.value)
