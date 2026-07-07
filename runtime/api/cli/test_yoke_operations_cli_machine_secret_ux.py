"""Installer-facing machine-secret UX tests for local CLI auth inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import github_machine


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


def _payload(cfg: Path) -> dict[str, Any]:
    return json.loads(cfg.read_text())


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _referenced_machine_secret_paths(cfg: Path) -> list[Path]:
    secrets_dir = cfg.parent / "secrets"
    paths: list[Path] = []
    for raw in _strings(_payload(cfg)):
        path = Path(raw).expanduser()
        if path.is_absolute() and _is_relative_to(path, secrets_dir):
            paths.append(path)
    return paths


def _assert_imported_machine_secret(
    cfg: Path,
    *,
    secret: str,
    captured,
    source_path: Path | None = None,
) -> None:
    config_text = cfg.read_text()
    assert secret not in config_text
    assert secret not in captured.out
    assert secret not in captured.err
    if source_path is not None:
        assert str(source_path) not in config_text

    matching_paths = [
        path for path in _referenced_machine_secret_paths(cfg)
        if path.is_file() and path.read_text() == secret + "\n"
    ]
    assert matching_paths
    for path in matching_paths:
        assert path.parent == cfg.parent / "secrets"
        assert path != source_path
        assert path.stat().st_mode & 0o777 == 0o600


def test_github_connect_positional_pat_imports_without_leaking(
    cfg, capsys, monkeypatch
) -> None:
    secret = "ghp_direct_machine_secret"
    monkeypatch.setattr(github_machine, "_verify", _fake_verify)

    rc = yoke_operations_cli.main([
        "github", "connect", secret, "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_imported_machine_secret(cfg, secret=secret, captured=captured)


def test_github_connect_token_file_imports_without_source_reference(
    cfg, tmp_path, capsys, monkeypatch
) -> None:
    secret = "ghp_file_machine_secret"
    source = tmp_path / "github.pat"
    source.write_text(secret + "\n")
    monkeypatch.setattr(github_machine, "_verify", _fake_verify)

    rc = yoke_operations_cli.main([
        "github", "connect", "--token-file", str(source),
        "--config", str(cfg),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    _assert_imported_machine_secret(
        cfg, secret=secret, captured=captured, source_path=source,
    )


def _fake_verify(
    _api_url: str, _token: str, *, github_repo: str | None = None
) -> dict[str, Any]:
    return {
        "identity": {"checked": True, "ok": True, "login": "machine-user", "id": 1},
        "access": {"owners": ["machine-user"], "repos": [], "repo_count": 0},
        "scopes": ["repo"],
    }
