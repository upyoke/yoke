"""Registered-checkout helper restoration after GitHub reconnect."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _alternate_profile_opener,
    _api_opener,
    _device_opener,
    _explicit_profile,
    _profile_opener,
)
from runtime.api.cli.test_github_git_credential_install import (
    _configured_repo,
    _git,
)
from yoke_cli.config import github_git_credentials, github_machine


def _register_checkout(config: Path, repo: Path, tmp_path: Path) -> None:
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload.update({
        "active_env": "stage",
        "connections": {"stage": {
            "transport": "https",
            "api_url": "https://stage.yoke.example",
            "credential_source": {
                "kind": "token_file", "path": str(tmp_path / "actor.token"),
            },
        }},
        "projects": [{
            "checkout": str(repo), "project_id": 1, "env": "stage",
        }],
    })
    config.write_text(json.dumps(payload), encoding="utf-8")
    _git(repo, "remote", "add", "origin", "https://github.com/octo/repo.git")


def test_disconnect_then_reconnect_restores_registered_checkout_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _register_checkout(config, repo, tmp_path)
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        "[credential]\n\thelper = ambient-helper\n", encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site",
    )
    configured = github_git_credentials.configure_repo_helper(
        repo, config_path=config,
    )

    github_machine.disconnect(config_path=config)
    assert _git(
        repo, "config", "--local", "--get-all", configured["key"], check=False,
    ).returncode == 1

    report = github_machine.connect(
        config_path=config,
        service_api_url="https://stage.yoke.example",
        profile_opener=_profile_opener,
        device_opener=_device_opener(), api_opener=_api_opener(installed=True),
        browser_open=lambda url: True, sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    values = _git(
        repo, "config", "--local", "--get-all", configured["key"],
    ).stdout.splitlines()
    assert report["repo_helpers_reattached"] == 1
    assert values[0] == ""
    assert github_git_credentials.STABLE_HELPER_FILE_NAME in values[1]
    assert _git(
        repo, "config", "--get-all", "credential.helper",
    ).stdout.strip() == "ambient-helper"


def test_failed_profile_replacement_keeps_existing_helper_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config, **_explicit_profile(),
        device_opener=_device_opener(), api_opener=_api_opener(installed=True),
        browser_open=lambda url: True, sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    _register_checkout(config, repo, tmp_path)
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site",
    )
    configured = github_git_credentials.configure_repo_helper(
        repo, config_path=config,
    )
    before_config = config.read_bytes()
    before_helper = _git(
        repo, "config", "--local", "--get-all", configured["key"],
    ).stdout

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="previous connection and credential were preserved",
    ):
        github_machine.connect(
            config_path=config,
            service_api_url="https://other.yoke.example",
            profile_opener=_alternate_profile_opener,
            replace_profile=True,
            device_opener=_device_opener(), api_opener=unavailable,
            browser_open=lambda url: True, sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert config.read_bytes() == before_config
    assert _git(
        repo, "config", "--local", "--get-all", configured["key"],
    ).stdout == before_helper
