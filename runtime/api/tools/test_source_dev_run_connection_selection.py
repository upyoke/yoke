"""Source commands preserve the caller's selected control-plane connection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.tools import _source_pythonpath, source_dev_run


ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"


def _select_administering_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": SERVED_ENV,
                "connections": {
                    SERVED_ENV: {"transport": "https"},
                    ADMIN_ENV: {
                        "transport": "local-postgres",
                        "prod": True,
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                    },
                },
            }
        )
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)


def _bind_current_source_lane(monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _source_pythonpath.repo_root(Path(__file__))
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda *_args: (root, None, None),
    )
    return root


def test_source_command_child_keeps_explicit_connection_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _select_administering_connection(monkeypatch, tmp_path)
    _bind_current_source_lane(monkeypatch)

    probe = (
        "from yoke_contracts.machine_config.runtime import active_env; "
        "print(active_env())"
    )
    assert source_dev_run.run(["python3", "-c", probe]) == 0

    captured = capfd.readouterr()
    assert captured.out.strip() == ADMIN_ENV


def test_prod_flagged_schema_refusal_still_fires_through_source_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _select_administering_connection(monkeypatch, tmp_path)
    _bind_current_source_lane(monkeypatch)
    probe = (
        "from yoke_contracts.schema_authority import "
        "refuse_without_serving_build_authority; "
        "refuse_without_serving_build_authority('converging a database schema')"
    )

    direct = subprocess.run(
        [sys.executable, "-c", probe],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct.returncode != 0
    assert f"refused on connection {ADMIN_ENV!r}" in direct.stderr

    assert source_dev_run.run(["python3", "-c", probe]) != 0
    through_runner = capfd.readouterr().err
    assert f"refused on connection {ADMIN_ENV!r}" in through_runner
    assert "deploy the build carrying this change" in through_runner
