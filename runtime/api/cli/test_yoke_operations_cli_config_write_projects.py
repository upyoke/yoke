"""CLI project-mapping writer tests (register + stamp-project-env)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


def _seed(cfg: Path, tmp_path: Path, env: str) -> None:
    token = tmp_path / f"{env}.token"
    token.write_text("tok\n")
    rc = yoke_operations_cli.main([
        "connection", "set", env,
        "--transport", "https",
        "--api-url", f"https://api.{env}.example",
        "--token-file", str(token),
        "--config", str(cfg),
    ])
    assert rc == 0


def test_project_register_maps_checkout(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "project", "register", str(repo),
        "--project-id", "7",
        "--config", str(cfg),
    ])

    assert rc == 0
    payload = json.loads(cfg.read_text())
    checkout = json.loads(capsys.readouterr().out)["checkout"]
    assert payload["projects"] == [
        {"checkout": checkout, "project_id": 7, "env": "prod"},
    ]


def test_project_register_refuses_board_scope(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    repo = tmp_path / "repo"
    repo.mkdir()
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "project", "register", str(repo),
        "--project-id", "7",
        "--board-scope", "all",
        "--config", str(cfg),
    ])

    assert rc == 1
    assert "board is retired" in capsys.readouterr().err


def test_stamp_project_env_stamps_untagged_entries(cfg, tmp_path, capsys) -> None:
    _seed(cfg, tmp_path, "prod")
    payload = json.loads(cfg.read_text())
    payload["projects"] = {"/checkout/legacy": {"project_id": 3}}
    cfg.write_text(json.dumps(payload), encoding="utf-8")
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "config", "stamp-project-env", "--config", str(cfg),
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["env"] == "prod"
    assert [row["checkout"] for row in result["stamped"]] == ["/checkout/legacy"]
    assert json.loads(cfg.read_text())["projects"] == [
        {"checkout": "/checkout/legacy", "project_id": 3, "env": "prod"},
    ]
