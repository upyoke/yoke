"""Stale-reference safety for local GitHub App config mutations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_cli.config import github_machine, github_machine_state
from yoke_cli.config import github_user_tokens, machine_config, secrets, writer
from yoke_contracts import github_app_installation_permissions
from yoke_contracts.machine_config import schema as contract


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _token_response(label: str) -> dict[str, Any]:
    return {
        "access_token": f"access-{label}",
        "expires_in": 28800,
        "refresh_token": f"refresh-{label}",
        "refresh_token_expires_in": 15552000,
        "scope": "",
    }


def _device_opener(label: str):
    responses = iter([
        {
            "device_code": f"device-{label}",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        _token_response(label),
    ])
    return lambda request, timeout: _Response(next(responses))


def _api_opener():
    permissions = {
        item.key: item.access for item in
        github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }

    def open_request(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"})
        if "/user/installations?" in url:
            return _Response({"installations": [{
                "id": 123,
                "account": {
                    "id": 9, "login": "octo-org", "type": "Organization",
                },
                "repository_selection": "selected",
                "permissions": permissions,
                "suspended_at": None,
            }]})
        if "/user/installations/123/repositories?" in url:
            return _Response({"repositories": [{
                "id": 456, "full_name": "octo-org/app",
                "default_branch": "main",
            }]})
        raise AssertionError(url)

    return open_request


def _seed_connection(config: Path, label: str) -> tuple[dict[str, Any], Path]:
    credential_id = label.encode("utf-8").hex().ljust(32, "0")[:32]
    credential = secrets.secret_path(
        f"github-app-user-{credential_id}", "json"
    )
    github_user_tokens.store_initial_token(credential, _token_response(label))
    github = {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": f"yoke-{label}",
        "client_id": "Iv1.local",
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": str(credential),
            "status": "authorized",
        },
    }
    return github, credential


def _install_seed(config: Path, label: str) -> tuple[dict[str, Any], Path]:
    github, credential = _seed_connection(config, label)
    writer.set_github(github, expected_credential_ref="", path=config)
    return github, credential


def test_concurrent_connect_keeps_winner_and_cleans_loser(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    first, first_credential = _install_seed(config, "first")
    winner, winner_credential = _seed_connection(config, "winner")
    original_set = writer.set_github
    raced = False

    def race_set(github, *, expected_credential_ref, path=None):
        nonlocal raced
        if not raced:
            raced = True
            original_set(
                winner,
                expected_credential_ref=github_machine_state.credential_ref(first),
                path=path,
            )
            github_machine_state.remove_owned_credential(first_credential)
        return original_set(
            github, expected_credential_ref=expected_credential_ref, path=path,
        )

    monkeypatch.setattr(writer, "set_github", race_set)
    before = {winner_credential}
    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.connect(
            config_path=config, client_id="Iv1.local", app_slug="yoke-loser",
            device_opener=_device_opener("loser"), api_opener=_api_opener(),
            browser_open=lambda url: True, sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    current = machine_config.github_config(config)
    assert current["app_slug"] == "yoke-winner"
    assert set(secrets.secrets_dir().glob("github-app-user-*.json")) == before


def test_status_refuses_to_overwrite_newer_connection(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    first, _ = _install_seed(config, "first")
    winner, winner_credential = _seed_connection(config, "winner")
    delegate = _api_opener()
    raced = False

    def race_during_live_check(request, timeout):
        nonlocal raced
        if not raced:
            raced = True
            writer.set_github(
                winner,
                expected_credential_ref=github_machine_state.credential_ref(first),
                path=config,
            )
        return delegate(request, timeout)

    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.status(
            config_path=config, api_opener=race_during_live_check,
        )

    current = machine_config.github_config(config)
    assert current["app_slug"] == "yoke-winner"
    assert Path(github_machine_state.credential_ref(current)) == winner_credential


def test_disconnect_deletes_credential_actually_removed_from_config(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    first, first_credential = _install_seed(config, "first")
    winner, winner_credential = _seed_connection(config, "winner")
    original_clear = writer.clear_github

    def race_clear(*, path=None):
        writer.set_github(
            winner,
            expected_credential_ref=github_machine_state.credential_ref(first),
            path=path,
        )
        return original_clear(path=path)

    monkeypatch.setattr(writer, "clear_github", race_clear)
    report = github_machine.disconnect(config_path=config)

    assert report["credential_removed"] is True
    assert first_credential.is_file()
    assert not winner_credential.exists()
    assert machine_config.github_config(config) == {}
    serialized = json.dumps(report)
    assert "refresh_credential_ref" not in serialized
    assert str(winner_credential) not in serialized
