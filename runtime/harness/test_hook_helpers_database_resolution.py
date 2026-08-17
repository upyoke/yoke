"""Connected-environment database resolution tests for hook helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from yoke_core.hooks.helpers import resolve_yoke_db
from yoke_core.domain import machine_config


class TestResolveYokeDb:
    def _binding(self, root: Path) -> Path:
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
                                "infra_dir": ".yoke/infra",
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
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_returns_empty_without_explicit_override(self):
        with mock.patch.dict(
            os.environ,
            {"YOKE_CONNECTED_ENV_DISABLE": "1"},
            clear=True,
        ):
            assert resolve_yoke_db() == ""

    def test_connected_postgres_binding_uses_no_sqlite_db(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        with mock.patch.dict(
            os.environ, {machine_config.CONFIG_FILE_ENV: str(binding)}, clear=True
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == ""

    def test_retired_canonical_yoke_db_env_returns_empty(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        canonical = root / "data" / "yoke.db"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.dict(
            os.environ,
            {"YOKE_DB": str(canonical), machine_config.CONFIG_FILE_ENV: str(binding)},
            clear=True,
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == ""

    def test_noncanonical_yoke_db_env_still_supports_fixtures(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        fixture = tmp_path / "fixture.db"
        with mock.patch.dict(
            os.environ,
            {"YOKE_DB": str(fixture), machine_config.CONFIG_FILE_ENV: str(binding)},
            clear=True,
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == str(fixture)
