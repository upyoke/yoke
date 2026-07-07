from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import machine_config, observe_db, yoke_connected_env


def _binding(root: Path) -> Path:
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "authority": {
                            "kind": "aws_aurora_postgres",
                            "infra_dir": "projects/yoke/infra",
                            "location": {
                                "stack": "yoke-prod",
                                "database_name": "yoke_prod",
                            },
                        },
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": "/tmp/yoke-prod-db-admin.pg.dsn",
                        },
                    },
                },
                "projects": {
                    str(root.resolve()): {
                        "project_id": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_normalize_observe_db_path_drops_retired_canonical_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    canonical = root / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)

    assert observe_db.normalize_observe_db_path(str(canonical)) is None


def test_normalize_observe_db_path_keeps_fixture_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    fixture = tmp_path / "fixture.db"

    assert observe_db.normalize_observe_db_path(str(fixture)) == str(fixture)
