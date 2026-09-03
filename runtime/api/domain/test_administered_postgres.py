"""Target identity for Postgres clusters administered by this machine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import administered_postgres
from yoke_core.domain import scratch_database_authority

ADMIN_ENV = "prod-db-admin"
ADMIN_DSN = "host=127.0.0.1 port=6547 dbname=yoke_prod user=admin"


def _configure(monkeypatch, tmp_path, *, selected: str = "local") -> None:
    dsn_file = tmp_path / "prod.dsn"
    dsn_file.write_text(ADMIN_DSN)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": "local",
                "connections": {
                    "local": {
                        "transport": "local-postgres",
                        "prod": False,
                    },
                    "prod": {"transport": "https", "prod": True},
                    ADMIN_ENV: {
                        "transport": "local-postgres",
                        "prod": True,
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn_file),
                        },
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                    },
                },
            }
        )
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, selected)


def test_raw_dsn_matching_administered_host_and_port_is_identified(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)

    target_dsn = "host=127.0.0.1 port=6547 dbname=a_test_database user=test"

    assert administered_postgres.administering_target(dsn=target_dsn) == ADMIN_ENV
    with pytest.raises(scratch_database_authority.ScratchDatabaseRefused):
        scratch_database_authority.refuse_scratch_database_on_administered_cluster(
            "yoke_test_run7xabc_raw",
            target_dsn=target_dsn,
        )


def test_target_is_compared_with_every_administered_connection(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)
    config = Path(machine_config_runtime.config_path())
    payload = json.loads(config.read_text())
    payload["connections"]["analytics-db-admin"] = {
        "transport": "local-postgres",
        "prod": True,
        "credential_source": {"kind": "env", "name": "ANALYTICS_ADMIN_DSN"},
    }
    config.write_text(json.dumps(payload))
    monkeypatch.setenv(
        "ANALYTICS_ADMIN_DSN",
        "host=127.0.0.1 port=6552 dbname=analytics",
    )

    assert (
        administered_postgres.administering_target(
            dsn="host=localhost port=6552 dbname=scratch"
        )
        == "analytics-db-admin"
    )


def test_database_name_and_credentials_do_not_change_cluster_identity(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)
    first = administered_postgres.endpoint_from_dsn(ADMIN_DSN)
    second = administered_postgres.endpoint_from_dsn(
        "host=127.0.0.1 port=6547 dbname=another password=different"
    )

    assert first == second


def test_different_port_is_not_the_administered_target(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)

    assert (
        administered_postgres.administering_target(
            dsn="host=127.0.0.1 port=6548 dbname=scratch"
        )
        == ""
    )


def test_live_connection_uses_the_same_target_predicate(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    connection = SimpleNamespace(
        info=SimpleNamespace(dsn_parameters={"host": "127.0.0.1", "port": "6547"})
    )

    assert (
        administered_postgres.administering_target(connection=connection) == ADMIN_ENV
    )


def test_selected_connection_remains_the_pre_connection_backstop(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path, selected=ADMIN_ENV)

    assert administered_postgres.administering_target() == ADMIN_ENV


def test_prod_https_selection_never_names_a_database_cluster(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path, selected="prod")

    assert administered_postgres.administering_target() == ""


def test_doctor_inventory_keeps_the_admin_credential_private(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)

    targets = administered_postgres.configured_administered_targets()

    assert [target.env for target in targets] == [ADMIN_ENV]
    assert targets[0].dsn == ADMIN_DSN
    assert ADMIN_DSN not in repr(targets[0])


def test_endpoint_inventory_survives_machine_config_isolation(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)

    child_env = administered_postgres.environment_with_administered_target_inventory(
        dict(os.environ)
    )
    inventory = child_env[administered_postgres.ADMINISTERED_TARGETS_ENV]
    assert json.loads(inventory)[ADMIN_ENV] == [["loopback", "6547"]]
    assert "user=admin" not in inventory
    assert "dbname=yoke_prod" not in inventory

    monkeypatch.setenv(administered_postgres.ADMINISTERED_TARGETS_ENV, inventory)
    monkeypatch.setenv(
        machine_config_runtime.CONFIG_FILE_ENV,
        str(tmp_path / "isolated" / "config.json"),
    )
    assert (
        administered_postgres.administering_target(
            dsn="host=127.0.0.1 port=6547 dbname=scratch"
        )
        == ADMIN_ENV
    )
