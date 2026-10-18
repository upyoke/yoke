"""Machine connection fixtures for connected-environment tests."""

import json
from pathlib import Path
import pytest
from yoke_core.domain import db_backend, machine_config, yoke_connected_env


def _binding(root: Path, dsn_file: Path, *, prod: bool | None = None) -> Path:
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = {
        "transport": "local-postgres",
        "authority": {
            "kind": "aws_aurora_postgres",
            "infra_dir": "projects/example/infra",
            "location": {
                "stack": "example-prod",
                "database_name": "example_prod",
            },
        },
        "credential_source": {
            "kind": "dsn_file",
            "path": str(dsn_file),
        },
    }
    if prod is not None:
        connection["prod"] = prod
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": connection,
                },
                "connection_projects": {
                    "prod-db-admin": [
                        {"checkout": str(root.resolve()), "project_id": 7}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        db_backend.PG_DSN_ENV,
        db_backend.PG_DSN_FILE_ENV,
        "YOKE_DB",
        machine_config.CONFIG_FILE_ENV,
        yoke_connected_env.DISABLE_ENV,
        yoke_connected_env.PYTEST_ENABLE_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
