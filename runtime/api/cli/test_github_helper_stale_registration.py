"""Stale checkout registrations warn without blocking CLI publication."""

import json

import pytest

from runtime.api.cli.test_cli_release_runtime import candidate
from runtime.api.cli.test_github_git_credential_install import _configured_repo
from runtime.api.cli.test_github_repo_helper_restore_missing_bundle import (
    _register_checkouts,
)
from yoke_cli.commands.adapters.github_credential_helper import (
    github_credential_helper_refresh,
)
from yoke_cli.config import cli_release_runtime, github_git_credentials
from yoke_cli.config.github_repo_helper_reconnect import restore_missing_bundle


@pytest.mark.parametrize("with_helper", [False, True])
def test_stale_folder_warns_and_candidate_activates(tmp_path, monkeypatch, with_helper):
    repo, config, _ = _configured_repo(tmp_path, monkeypatch)
    stale = tmp_path / "stale checkout"
    stale.mkdir()
    _register_checkouts(config, [stale, repo], tmp_path)
    if with_helper:
        monkeypatch.setattr(
            github_git_credentials, "_helper_dir", lambda: tmp_path / "helper"
        )
        github_git_credentials.configure_repo_helper(repo, config_path=config)
    before = config.read_bytes()

    receipt = restore_missing_bundle(config)

    assert "error" not in receipt
    assert receipt["configured"] is with_helper
    assert receipt["repaired"] is with_helper
    assert len(receipt["warnings"]) == 1
    assert receipt["warnings"][0].startswith("not_a_repo:")
    assert f"yoke project uninstall '{stale}'" in receipt["warnings"][0]
    assert config.read_bytes() == before

    root = tmp_path / "runtime"
    generation = candidate(root, "1.0")
    main = generation / "tools/yoke-cli/lib"
    module = next(main.glob("python*/site-packages/yoke_cli/main.py"))
    module.write_text(
        module.read_text().replace(
            "json.dumps({'configured': False})", f"json.dumps({receipt!r})"
        )
    )
    cli_release_runtime.activate(root, generation, tmp_path / "bin", "1.0")
    assert (root / "current").resolve() == generation


def test_valid_repository_with_broken_config_still_refuses(tmp_path, monkeypatch):
    repo, config, _ = _configured_repo(tmp_path, monkeypatch)
    _register_checkouts(config, [repo], tmp_path)
    (repo / ".git/config").write_text("[broken\n")

    receipt = restore_missing_bundle(config)

    assert receipt["configured"] is None
    assert receipt["repaired"] is False
    assert "could not read git config" in receipt["error"]
    assert "warnings" not in receipt


def test_refresh_prints_stale_warning_in_text_and_json(tmp_path, monkeypatch, capsys):
    repo, config, _ = _configured_repo(tmp_path, monkeypatch)
    stale = tmp_path / "stale"
    stale.mkdir()
    _register_checkouts(config, [stale, repo], tmp_path)

    assert github_credential_helper_refresh(["--config", str(config)]) == 0
    assert "warning: not_a_repo:" in capsys.readouterr().out
    assert github_credential_helper_refresh(["--config", str(config), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"][0].startswith("not_a_repo:")
