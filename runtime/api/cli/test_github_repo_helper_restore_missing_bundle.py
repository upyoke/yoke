"""Tests for repairing a git credential-helper bundle a reinstall wiped."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from runtime.api.cli.test_github_git_credential_install import (
    _configured_repo,
    _git,
)
from runtime.api.cli.test_github_repo_helper_reconnect import _register_checkout
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_repo_config
from yoke_cli.config import github_repo_helper_reconnect


def test_restore_missing_bundle_rebuilds_a_wiped_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reinstall wipes site-packages while git config still names the helper."""
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _register_checkout(config, repo, tmp_path)
    site = tmp_path / "site"
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)
    configured = github_git_credentials.configure_repo_helper(
        repo,
        config_path=config,
    )
    helper_path = site / github_git_credentials.STABLE_HELPER_FILE_NAME
    assert helper_path.is_file()
    before_helper_value = _git(
        repo,
        "config",
        "--local",
        "--get-all",
        configured["key"],
    ).stdout

    # Simulate `uv tool install --reinstall` wiping the tool venv: the
    # runtime-written bundle is gone, but nothing touched git config.
    shutil.rmtree(site)
    assert not helper_path.is_file()

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result == {"configured": True, "repaired": True}
    assert helper_path.is_file()
    assert (
        _git(
            repo,
            "config",
            "--local",
            "--get-all",
            configured["key"],
        ).stdout
        == before_helper_value
    )


def test_restore_missing_bundle_is_a_legitimate_no_op_when_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    repo = tmp_path / "plain-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    config = home / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [{"checkout": str(repo), "project_id": 1, "env": "stage"}],
            }
        ),
        encoding="utf-8",
    )
    site = tmp_path / "never-created-site"
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result == {"configured": False, "repaired": False}
    assert not site.exists()


def test_restore_missing_bundle_surfaces_a_genuine_repair_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _register_checkout(config, repo, tmp_path)
    site = tmp_path / "site"
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)
    github_git_credentials.configure_repo_helper(repo, config_path=config)
    shutil.rmtree(site)

    def broken_install(_site_dir=None):
        raise github_git_credentials.GitHubCredentialBundleError("disk full")

    monkeypatch.setattr(
        github_git_credentials,
        "install_stable_helper",
        broken_install,
    )

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result == {
        "configured": True,
        "repaired": False,
        "error": "disk full",
    }


def test_restore_missing_bundle_refuses_an_unverifiable_moved_runtime_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior runtime's helper/bundle is gone too (e.g. a Python minor bump
    alongside the reinstall) -- the value still names the stable helper
    filename, but nothing is left to read to prove it is Yoke's."""
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    config = home / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [{"checkout": str(repo), "project_id": 1, "env": "stage"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_site_dir",
        lambda: tmp_path / "current-site",
    )
    gone_python = tmp_path / "gone-runtime" / "bin" / "python3.11"
    gone_helper = (
        tmp_path
        / "gone-runtime"
        / "site-packages"
        / github_git_credentials.STABLE_HELPER_FILE_NAME
    )
    value = f"!{gone_python} {gone_helper} --config {config}"
    _git(
        repo,
        "config",
        "--local",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        value,
    )

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result["configured"] is None
    assert result["repaired"] is False
    assert str(repo) in result["error"]
    assert "reconnect" in result["error"].lower()


def test_restore_missing_bundle_reports_unreadable_git_config_distinctly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    config = home / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [{"checkout": str(repo), "project_id": 1, "env": "stage"}],
            }
        ),
        encoding="utf-8",
    )

    def broken_helper_keys(_root):
        raise github_repo_config.GitHubRepoConfigError("git config unreadable")

    monkeypatch.setattr(github_repo_config, "helper_keys", broken_helper_keys)

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result["configured"] is None
    assert result["repaired"] is False
    assert str(repo) in result["error"]
    assert "could not read git config" in result["error"]


def test_restore_missing_bundle_reports_unreadable_machine_config_distinctly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("not valid json", encoding="utf-8")

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result["configured"] is None
    assert result["repaired"] is False
    assert "machine config" in result["error"]


def _register_checkouts(config: Path, repos: list[Path], tmp_path: Path) -> None:
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload.update(
        {
            "active_env": "stage",
            "connections": {
                "stage": {
                    "transport": "https",
                    "api_url": "https://stage.yoke.example",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(tmp_path / "actor.token"),
                    },
                }
            },
            "projects": [
                {"checkout": str(repo), "project_id": 1, "env": "stage"}
                for repo in repos
            ],
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")


def _write_ambiguous_reference(repo: Path, config: Path, tmp_path: Path) -> None:
    gone_python = tmp_path / "gone-runtime" / "bin" / "python3.11"
    gone_helper = (
        tmp_path
        / "gone-runtime"
        / "site-packages"
        / github_git_credentials.STABLE_HELPER_FILE_NAME
    )
    value = f"!{gone_python} {gone_helper} --config {config}"
    _git(
        repo,
        "config",
        "--local",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        value,
    )


def _assert_mixed_checkout_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    match_first: bool,
) -> None:
    """A known-repairable checkout and an unresolvable one, in either order:
    the repair still happens, and the unresolved checkout is still reported
    rather than dropped by a result that reads as a clean success."""
    repo_match, config, _credential = _configured_repo(tmp_path, monkeypatch)
    repo_ambiguous = tmp_path / "ambiguous-repo"
    repo_ambiguous.mkdir()
    _git(repo_ambiguous, "init", "--initial-branch", "main")
    ordered = (
        [repo_match, repo_ambiguous] if match_first else [repo_ambiguous, repo_match]
    )
    _register_checkouts(config, ordered, tmp_path)

    site = tmp_path / "site"
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)
    github_git_credentials.configure_repo_helper(repo_match, config_path=config)
    shutil.rmtree(site)
    _write_ambiguous_reference(repo_ambiguous, config, tmp_path)

    result = github_repo_helper_reconnect.restore_missing_bundle(config)

    assert result["configured"] is True
    assert result["repaired"] is True
    assert str(repo_ambiguous) in result["error"]
    assert (site / github_git_credentials.STABLE_HELPER_FILE_NAME).is_file()


def test_restore_missing_bundle_repairs_and_reports_unresolved_match_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_mixed_checkout_repair(tmp_path, monkeypatch, match_first=True)


def test_restore_missing_bundle_repairs_and_reports_unresolved_ambiguous_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_mixed_checkout_repair(tmp_path, monkeypatch, match_first=False)
