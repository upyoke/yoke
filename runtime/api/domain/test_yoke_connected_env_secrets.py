"""Credential sources a machine connection may declare."""

import json
from pathlib import Path

import pytest

from runtime.api.domain.yoke_connected_env_test_support import _clean_env
from runtime.api.fixtures.machine_config_test import select_machine_config_file
from yoke_core.domain import db_backend, yoke_connected_env


def test_removed_aws_secrets_manager_source_refuses_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    repo = tmp_path / "repo"
    binding = repo / ".yoke" / "config.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                        "credential_source": {
                            "kind": "aws_secrets_manager",
                            "secret_arn": "arn:aws:secretsmanager:example",
                            "region": "us-east-1",
                            "project": "yoke",
                        },
                    },
                },
                "connection_projects": {
                    "prod-db-admin": [{"checkout": str(repo.resolve()), "project_id": 1}]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    select_machine_config_file(monkeypatch, binding)

    with pytest.raises(yoke_connected_env.ConnectedEnvError) as exc:
        yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )

    assert "credential_source.kind must be one of" in str(exc.value)
    assert "aws_secrets_manager" not in str(exc.value).split("one of", 1)[1]
