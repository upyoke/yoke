"""Environment boundary tests for migration rehearsal commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import migration_apply_verify


def test_rehearsal_command_replaces_admin_selection_and_keeps_validation_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": "prod",
                "connections": {
                    "prod": {"transport": "https"},
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "prod": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    monkeypatch.setenv("REHEARSAL_PARENT_CONTEXT", "retained")
    captured: dict[str, object] = {}

    def _run(command: str, **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(migration_apply_verify.subprocess, "run", _run)
    validation_dsn = "postgresql://validation.example/rehearsal"

    outcomes, error = migration_apply_verify.run_rehearsal_commands(
        ["pytest -q runtime/api/domain"],
        env_var="APPLICATION_DATABASE_URL",
        validation_db_path=validation_dsn,
        cwd=tmp_path,
    )

    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env[ENV_OVERRIDE] == "prod"
    assert child_env["APPLICATION_DATABASE_URL"] == validation_dsn
    assert child_env["YOKE_DB"] == validation_dsn
    assert child_env["REHEARSAL_PARENT_CONTEXT"] == "retained"
    assert error is None
    assert outcomes[0]["returncode"] == 0
