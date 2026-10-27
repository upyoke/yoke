"""CLI project-mapping writer tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.commands.adapters import config_write_project


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


def _seed(cfg: Path, tmp_path: Path, env: str) -> None:
    token = tmp_path / f"{env}.token"
    token.write_text("tok\n")
    rc = yoke_operations_cli.main(
        [
            "connection",
            "set",
            env,
            "--transport",
            "https",
            "--api-url",
            f"https://api.{env}.example",
            "--token-file",
            str(token),
            "--config",
            str(cfg),
        ]
    )
    assert rc == 0


def test_project_register_maps_checkout(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "project",
            "register",
            str(repo),
            "--project-id",
            "7",
            "--config",
            str(cfg),
        ]
    )

    assert rc == 0
    payload = json.loads(cfg.read_text())
    checkout = str(repo.resolve())
    assert f"checkout: {checkout}" in capsys.readouterr().out
    assert payload["connection_projects"]["prod"] == [
        {"checkout": checkout, "project_id": 7}
    ]


def test_global_env_registers_colliding_ids_without_moving_the_default(
    cfg, tmp_path, monkeypatch
) -> None:
    _seed(cfg, tmp_path, "prod")
    _seed(cfg, tmp_path, "other")
    monkeypatch.setenv("YOKE_ENV", "prod")
    checkouts = {}
    for env in ("other", "prod"):
        checkout = tmp_path / env
        checkout.mkdir()
        checkouts[env] = checkout
        assert (
            yoke_operations_cli.main(
                [
                    "--env",
                    env,
                    "project",
                    "register",
                    str(checkout),
                    "--project-id",
                    "7",
                ]
            )
            == 0
        )
    payload = json.loads(cfg.read_text())
    assert payload["active_env"] == "prod"
    assert payload["connection_projects"] == {
        env: [{"checkout": str(checkout.resolve()), "project_id": 7}]
        for env, checkout in checkouts.items()
    }
    assert os.environ["YOKE_ENV"] == "prod"


def test_project_register_refuses_board_scope(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "project",
            "register",
            str(repo),
            "--project-id",
            "7",
            "--board-scope",
            "all",
            "--config",
            str(cfg),
        ]
    )

    assert rc == 1
    assert "board is retired" in capsys.readouterr().err


def test_project_register_reassign_delegates_authority_to_writer(cfg, tmp_path):
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch.object(config_write_project.writer, "register_project") as register:
        register.return_value = {}
        assert (
            yoke_operations_cli.main(
                [
                    "project",
                    "register",
                    str(repo),
                    "--project-id",
                    "7",
                    "--reassign",
                    "--config",
                    str(cfg),
                ]
            )
            == 0
        )
    register.assert_called_once_with(
        str(repo),
        7,
        board_scope=None,
        board_render_path=None,
        reassign=True,
        path=str(cfg),
    )
