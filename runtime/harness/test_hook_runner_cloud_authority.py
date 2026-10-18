from __future__ import annotations

import json
from pathlib import Path

from yoke_core.hooks import codex_payload as codex_hooks_payload
from yoke_core.hooks import target

from runtime.api.fixtures.machine_config_test import select_machine_config_file


def _binding(root: Path) -> Path:
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connection_projects": {
                    "prod-db-admin": [{"checkout": str(root), "project_id": 1}]
                },
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


def test_registered_checkout_marks_workspace_as_yoke_without_sqlite_db(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    select_machine_config_file(monkeypatch, str(binding))

    assert target.is_yoke_target(str(root), "") is True


def test_codex_target_gate_uses_shared_checkout_detection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("YOKE_DB", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    select_machine_config_file(monkeypatch, str(binding))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == ""
    assert codex_hooks_payload.is_yoke_target(str(root), "") is True


def test_codex_resolver_ignores_retired_canonical_yoke_db_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    select_machine_config_file(monkeypatch, str(binding))
    canonical = root / "data" / "yoke.db"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YOKE_DB", str(canonical))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == ""


def test_codex_resolver_keeps_noncanonical_fixture_yoke_db_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _binding(root)
    select_machine_config_file(monkeypatch, str(binding))
    fixture = tmp_path / "fixture.db"
    monkeypatch.setenv("YOKE_DB", str(fixture))

    assert codex_hooks_payload.resolve_yoke_db(str(root)) == str(fixture)
