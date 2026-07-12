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
    def __init__(self, payload: dict[str, Any], *, url: str = "") -> None:
        self.payload = payload
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self, size: int = -1) -> bytes:
        body = json.dumps(self.payload).encode("utf-8")
        return body[:size] if size >= 0 else body

    def geturl(self) -> str:
        return self.url


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
    return lambda request, timeout: _Response(
        next(responses), url=request.full_url,
    )


def _api_opener():
    permissions = {
        item.key: item.access for item in
        github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }

    def open_request(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"}, url=url)
        if "/user/installations?" in url:
            return _Response({"installations": [{
                "id": 123,
                "app_id": 123,
                "app_slug": "yoke-local",
                "html_url": (
                    "https://github.com/organizations/octo-org/"
                    "settings/installations/123"
                ),
                "account": {
                    "id": 9, "login": "octo-org", "type": "Organization",
                },
                "repository_selection": "selected",
                "permissions": permissions,
                "suspended_at": None,
            }]}, url=url)
        if "/user/installations/123/repositories?" in url:
            return _Response({"repositories": [{
                "id": 456, "full_name": "octo-org/app",
                "default_branch": "main",
                "private": True,
            }]}, url=url)
        raise AssertionError(url)

    return open_request


def _seed_connection(
    config: Path,
    label: str,
    *,
    service_api_url: str | None = None,
) -> tuple[dict[str, Any], Path]:
    credential_id = label.encode("utf-8").hex().ljust(32, "0")[:32]
    credential = secrets.secret_path(
        f"github-app-user-{credential_id}", "json"
    )
    github_user_tokens.store_initial_token(
        credential,
        _token_response(label),
        device_flow_completed=True,
        config_path=config,
    )
    github = {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke-local",
        "app_id": 123,
        "client_id": "Iv1.local",
        "profile_source": (
            contract.GITHUB_PROFILE_SOURCE_SERVICE
            if service_api_url
            else contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT
        ),
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": str(credential),
            "status": "authorized",
        },
    }
    if service_api_url:
        github["profile_service_api_url"] = service_api_url
    return github, credential


def _install_seed(
    config: Path,
    label: str,
    *,
    service_api_url: str | None = None,
) -> tuple[dict[str, Any], Path]:
    github, credential = _seed_connection(
        config, label, service_api_url=service_api_url,
    )
    writer.set_github(github, expected_credential_ref="", path=config)
    return github, credential


def test_concurrent_connect_keeps_winner_and_cleans_loser(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    first, first_credential = _install_seed(config, "first")
    winner_credential: Path | None = None
    original_set = writer.set_github
    raced = False

    def race_set(
        github,
        *,
        expected_credential_ref,
        expected_profile_identity=None,
        path=None,
    ):
        nonlocal raced, winner_credential
        if not raced:
            raced = True
            winner, winner_credential = _seed_connection(config, "winner")
            original_set(
                winner,
                expected_credential_ref=github_machine_state.credential_ref(first),
                path=path,
            )
        return original_set(
            github,
            expected_credential_ref=expected_credential_ref,
            expected_profile_identity=expected_profile_identity,
            path=path,
        )

    monkeypatch.setattr(writer, "set_github", race_set)
    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.connect(
            config_path=config,
            client_id="Iv1.local",
            app_slug="yoke-local",
            app_id=123,
            api_url=contract.DEFAULT_GITHUB_API_URL,
            web_url=contract.DEFAULT_GITHUB_WEB_URL,
            device_opener=_device_opener("loser"), api_opener=_api_opener(),
            browser_open=lambda url: True, sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    current = machine_config.github_config(config)
    assert winner_credential is not None
    assert current["app_slug"] == "yoke-local"
    assert github_machine_state.credential_ref(current) == str(winner_credential)
    assert set(secrets.secrets_dir().glob("github-app-user-*.json")) == {
        winner_credential,
    }
    assert not first_credential.exists()


def test_status_refuses_to_overwrite_newer_connection(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    service_api_url = "https://api.upyoke.com"
    first, _ = _install_seed(
        config, "first", service_api_url=service_api_url,
    )
    winner_credential: Path | None = None
    delegate = _api_opener()
    raced = False

    def race_during_live_check(request, timeout):
        nonlocal raced, winner_credential
        if not raced:
            raced = True
            winner, winner_credential = _seed_connection(
                config, "winner", service_api_url=service_api_url,
            )
            writer.set_github(
                winner,
                expected_credential_ref=github_machine_state.credential_ref(first),
                path=config,
            )
        return delegate(request, timeout)

    def profile_open(request, timeout):
        return _Response({
            "github_app": {
                "available": True,
                "client_id": "Iv1.local",
                "app_slug": "yoke-local",
                "app_id": 123,
                "api_url": contract.DEFAULT_GITHUB_API_URL,
                "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            }
        }, url=request.full_url)

    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.status(
            config_path=config,
            service_api_url=service_api_url,
            api_opener=race_during_live_check,
            profile_opener=profile_open,
            token_opener=lambda request, timeout: _Response(
                _token_response("status"), url=request.full_url,
            ),
        )

    current = machine_config.github_config(config)
    assert winner_credential is not None
    assert current["app_slug"] == "yoke-local"
    assert Path(github_machine_state.credential_ref(current)) == winner_credential


def test_disconnect_cas_failure_keeps_winning_connection(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    first, first_credential = _install_seed(config, "first")
    winner_credential: Path | None = None
    original_clear = writer.clear_github

    def race_clear(*, expected_credential_ref, path=None):
        nonlocal winner_credential
        winner, winner_credential = _seed_connection(config, "winner")
        writer.set_github(
            winner,
            expected_credential_ref=github_machine_state.credential_ref(first),
            path=path,
        )
        return original_clear(
            expected_credential_ref=expected_credential_ref,
            path=path,
        )

    monkeypatch.setattr(writer, "clear_github", race_clear)
    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.disconnect(config_path=config)

    assert winner_credential is not None
    assert not first_credential.is_file()
    assert winner_credential.is_file()
    assert machine_config.github_config(config)["app_slug"] == "yoke-local"


def test_connect_cas_failure_cleans_new_credential_and_preserves_old(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    _first, first_credential = _install_seed(config, "first")

    def fail_config_write(*args, **kwargs):
        raise writer.MachineConfigWriteError("machine config changed")

    monkeypatch.setattr(writer, "set_github", fail_config_write)
    with pytest.raises(github_machine.GitHubMachineError, match="changed"):
        github_machine.connect(
            config_path=config,
            client_id="Iv1.local",
            app_slug="yoke-local",
            app_id=123,
            api_url=contract.DEFAULT_GITHUB_API_URL,
            web_url=contract.DEFAULT_GITHUB_WEB_URL,
            device_opener=_device_opener("replacement"),
            api_opener=_api_opener(),
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert first_credential.exists()
    assert machine_config.github_config(config)["authorization"][
        "refresh_credential_ref"
    ] == str(first_credential)
    assert list(secrets.secrets_dir().glob("github-app-user-*.json")) == [
        first_credential
    ]
