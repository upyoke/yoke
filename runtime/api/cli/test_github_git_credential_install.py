from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import github_git_credentials
from yoke_contracts import github_app_tokens, github_origin
from yoke_contracts.machine_config import schema as contract


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
    )


def _configured_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    credential = home / "secrets" / "github-app-user.json"
    github_git_credential_store.write_credential_document(credential, {
        "schema_version": 1,
        "access_token": "access-secret",
        "expires_at": "2099-07-09T17:00:00+00:00",
        "refresh_token": "refresh-secret",
        "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        "scope": "",
        "token_type": "bearer",
    })
    config = home / "config.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            "app_slug": "yoke",
            "client_id": "Iv1.local",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": str(credential),
                "status": "authorized",
            },
        },
    }), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    return repo, config, credential


def test_configure_helper_preserves_global_helpers_for_other_hosts(
    tmp_path: Path, monkeypatch,
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
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site",
    )

    report = github_git_credentials.configure_repo_helper(
        repo, config_path=config,
    )

    assert report["configured"] is True
    assert str(credential) not in json.dumps(report)
    generic = _git(repo, "config", "--get-all", "credential.helper")
    assert generic.stdout.strip() == "global-helper"
    local_generic = _git(
        repo, "config", "--local", "--get-all", "credential.helper",
        check=False,
    )
    assert local_generic.returncode == 1
    github_helpers = _git(
        repo, "config", "--local", "--get-all", report["key"],
    ).stdout.splitlines()
    assert github_helpers[0] == ""
    assert github_git_credentials.STABLE_HELPER_FILE_NAME in github_helpers[1]


def test_helper_bundle_failure_keeps_entrypoint_unpublished(
    tmp_path: Path, monkeypatch,
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    helper = site / github_git_credentials.STABLE_HELPER_FILE_NAME
    helper.write_text("old complete entrypoint\n", encoding="utf-8")
    real_replace = github_git_credentials._atomic_replace_source
    attempted: list[str] = []

    def fail_before_store(source: Path, target: Path) -> None:
        attempted.append(target.name)
        if target.name == github_git_credentials.STABLE_STORE_FILE_NAME:
            raise OSError("simulated publish failure")
        real_replace(source, target)

    monkeypatch.setattr(
        github_git_credentials, "_atomic_replace_source", fail_before_store,
    )

    with pytest.raises(OSError, match="simulated publish failure"):
        github_git_credentials.install_stable_helper(site)

    assert helper.read_text(encoding="utf-8") == "old complete entrypoint\n"
    assert github_git_credentials.STABLE_HELPER_FILE_NAME not in attempted
    assert not list(site.glob("*.tmp"))


def test_concurrent_helper_bundle_installs_publish_complete_sources(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"

    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(
            lambda _index: github_git_credentials.install_stable_helper(site),
            range(8),
        ))

    assert len(set(paths)) == 1
    expected = {
        github_git_credentials.STABLE_ORIGIN_FILE_NAME: Path(
            github_origin.__file__
        ),
        github_git_credentials.STABLE_TOKEN_CONTRACT_NAME: Path(
            github_app_tokens.__file__
        ),
        github_git_credentials.STABLE_FILE_IO_NAME: Path(
            github_git_credential_file.__file__
        ),
        github_git_credentials.STABLE_STORE_FILE_NAME: Path(
            github_git_credential_store.__file__
        ),
        github_git_credentials.STABLE_HELPER_FILE_NAME: Path(
            github_git_credential_helper.__file__
        ),
    }
    for name, source in expected.items():
        assert (site / name).read_bytes() == source.read_bytes()
    assert not list(site.glob("*.tmp"))
