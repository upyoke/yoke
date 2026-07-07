from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import machine_config
from runtime.harness.codex import codex_hooks_payload
from runtime.harness.hook_runner import target


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


def test_connected_env_marks_workspace_as_yoke_without_sqlite_db(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))

    assert target.is_yoke_target(str(root), "") is True


def test_codex_target_gate_uses_shared_connected_env_detection(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.delenv("YOKE_DB", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == ""
    assert codex_hooks_payload.is_yoke_target(str(root), "") is True


def test_codex_resolver_ignores_retired_canonical_yoke_db_env(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    canonical = root / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YOKE_DB", str(canonical))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == ""


def test_codex_resolver_keeps_noncanonical_fixture_yoke_db_env(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    fixture = tmp_path / "fixture.db"
    monkeypatch.setenv("YOKE_DB", str(fixture))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == str(fixture)
