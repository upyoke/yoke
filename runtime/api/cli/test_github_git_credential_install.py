from __future__ import annotations

from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo as _configured_repo,
    _git as _git,
)


import json
from pathlib import Path

import pytest

from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_machine
from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract


def test_configure_helper_preserves_global_helpers_for_other_hosts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, config, credential = _configured_repo(tmp_path, monkeypatch)
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        "[credential]\n\thelper = global-helper\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_dir",
        lambda: tmp_path / "site",
    )

    report = github_git_credentials.configure_repo_helper(
        repo,
        config_path=config,
    )

    assert report["configured"] is True
    assert str(credential) not in json.dumps(report)
    generic = _git(repo, "config", "--get-all", "credential.helper")
    assert generic.stdout.strip() == "global-helper"
    local_generic = _git(
        repo,
        "config",
        "--local",
        "--get-all",
        "credential.helper",
        check=False,
    )
    assert local_generic.returncode == 1
    github_helpers = _git(
        repo,
        "config",
        "--local",
        "--get-all",
        report["key"],
    ).stdout.splitlines()
    assert github_helpers[0] == ""
    assert github_git_credentials.STABLE_HELPER_FILE_NAME in github_helpers[1]


def test_disconnect_removes_url_reset_and_restores_ambient_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload.update(
        {
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "api_url": "https://api.upyoke.com",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(tmp_path / "prod.token"),
                    },
                },
            },
            "connection_projects": {"prod": [{"checkout": str(repo), "project_id": 1}]},
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        "[credential]\n\thelper = ambient-helper\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_dir",
        lambda: tmp_path / "site",
    )
    configured = github_git_credentials.configure_repo_helper(
        repo,
        config_path=config,
    )

    report = github_machine.disconnect(config_path=config)

    assert report["repo_helpers_removed"] == 1
    local = _git(
        repo,
        "config",
        "--local",
        "--get-all",
        configured["key"],
        check=False,
    )
    assert local.returncode == 1
    assert _git(repo, "config", "--get-all", "credential.helper").stdout.strip() == (
        "ambient-helper"
    )


def test_helper_cleanup_retains_and_reports_lookalike_user_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connection_projects"] = {
        "local": [{"checkout": str(repo), "project_id": 1}]
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    key = github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY
    lookalike = (
        "!python /tmp/user-"
        f"{github_git_credentials.STABLE_HELPER_FILE_NAME} --config {config}"
    )
    _git(repo, "config", "--local", "--replace-all", key, "")
    _git(repo, "config", "--local", "--add", key, lookalike)

    report = github_git_credentials.remove_known_repo_helpers(
        config_path=config,
    )

    assert report == {"removed": 0, "failed": 1}
    assert _git(
        repo,
        "config",
        "--local",
        "--get-all",
        key,
    ).stdout.splitlines() == ["", lookalike]


def test_disconnect_removes_helpers_from_all_registered_checkouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, config, _credential = _configured_repo(tmp_path, monkeypatch)
    second = tmp_path / "second"
    second.mkdir()
    _git(second, "init", "--initial-branch", "main")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload.update(
        {
            "active_env": "prod",
            "connections": {
                env: {
                    "transport": "https",
                    "api_url": f"https://api.{env}.upyoke.com",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(tmp_path / f"{env}.token"),
                    },
                }
                for env in ("prod", "stage")
            },
            "connection_projects": {
                "prod": [
                    {"checkout": str(first), "project_id": 1},
                    {"checkout": str(second), "project_id": 2},
                ]
            },
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_dir",
        lambda: tmp_path / "site",
    )
    configured = [
        github_git_credentials.configure_repo_helper(root, config_path=config)
        for root in (first, second)
    ]

    report = github_machine.disconnect(config_path=config)

    assert report["repo_helpers_removed"] == 2
    for root, item in zip((first, second), configured, strict=True):
        assert (
            _git(
                root,
                "config",
                "--local",
                "--get-all",
                item["key"],
                check=False,
            ).returncode
            == 1
        )


def test_all_registered_checkouts_filters_missing_paths(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": "local",
                "connection_projects": {
                    "local": [
                        {"checkout": str(checkout), "project_id": 1},
                        {"checkout": str(tmp_path / "missing"), "project_id": 2},
                    ]
                },
            }
        )
    )
    assert machine_config.all_registered_checkouts(config, existing_only=True) == [
        checkout.resolve()
    ]


def test_all_registered_checkouts_refuses_invalid_config(tmp_path: Path) -> None:
    import pytest

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": "local",
                "connection_projects": {"local": [{"checkout": "", "project_id": 1}]},
            }
        )
    )
    with pytest.raises(
        contract.MachineConfigContractError,
        match="project_checkout_invalid.*repair projects",
    ):
        machine_config.all_registered_checkouts(config)
