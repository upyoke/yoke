# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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


def _payload(cfg: Path) -> dict:
    return json.loads(cfg.read_text())


def _secret_path(cfg: Path, env: str, suffix: str = "token") -> Path:
    return cfg.parent / "secrets" / f"{env}.{suffix}"


def _assert_auth_token_imported(cfg: Path, env: str, secret: str, captured) -> None:
    token_path = _secret_path(cfg, env)
    assert token_path.is_file()
    assert token_path.read_text() == secret + "\n"
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert token_path.parent.stat().st_mode & 0o777 == 0o700

    payload = _payload(cfg)
    assert payload["connections"][env]["credential_source"] == {
        "kind": "token_file",
        "path": str(token_path),
    }
    assert secret not in cfg.read_text()
    assert secret not in captured.out
    assert secret not in captured.err


def _assert_dsn_imported(cfg: Path, env: str, dsn: str, captured) -> None:
    dsn_path = _secret_path(cfg, env, "dsn")
    assert dsn_path.is_file()
    assert dsn_path.read_text() == dsn + "\n"
    assert dsn_path.stat().st_mode & 0o777 == 0o600
    assert dsn_path.parent.stat().st_mode & 0o777 == 0o700

    payload = _payload(cfg)
    assert payload["connections"][env]["credential_source"] == {
        "kind": "dsn_file",
        "path": str(dsn_path),
    }
    assert dsn not in cfg.read_text()
    assert dsn not in captured.out
    assert dsn not in captured.err
