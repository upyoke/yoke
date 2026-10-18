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


def _verify_answer(success: bool):
    from types import SimpleNamespace

    return SimpleNamespace(
        success=success,
        error=None
        if success
        else SimpleNamespace(
            code="steering_seat_required",
            message=(
                "Moving a registered project's checkout requires a live steering "
                "seat for project 7. Recovery: yoke claims steering acquire "
                "--project 7"
            ),
        ),
    )


def _register_reassign(cfg, repo, *, seated: bool):
    with (
        patch.object(config_write_project, "ensure_handlers_loaded"),
        patch.object(
            config_write_project,
            "call_dispatcher",
            return_value=_verify_answer(seated),
        ) as dispatch,
    ):
        rc = yoke_operations_cli.main(
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
    assert dispatch.call_args.kwargs["function_id"] == "claims.steering.verify"
    assert dispatch.call_args.kwargs["target"].project_id == "7"
    return rc


def test_project_register_reassign_refused_without_steering_seat(
    cfg,
    tmp_path,
    capsys,
) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = _register_reassign(cfg, repo, seated=False)

    assert rc == 1
    err = capsys.readouterr().err
    assert "steering_seat_required" in err
    assert "yoke claims steering acquire --project 7" in err
    assert json.loads(cfg.read_text()).get("projects", []) == []


def test_project_register_reassign_allowed_with_steering_seat(
    cfg,
    tmp_path,
    capsys,
) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = _register_reassign(cfg, repo, seated=True)

    assert rc == 0
    checkout = str(repo.resolve())
    assert f"checkout: {checkout}" in capsys.readouterr().out
    assert json.loads(cfg.read_text())["connection_projects"]["prod"] == [
        {"checkout": checkout, "project_id": 7}
    ]
