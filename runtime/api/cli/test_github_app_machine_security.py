from __future__ import annotations

from runtime.api.cli.github_app_machine_security_test_support import (_Response as _Response, _configured_machine as _configured_machine, _empty_installation_opener as _empty_installation_opener, _profile_opener as _profile_opener, _refresh_opener as _refresh_opener)
from runtime.api.cli.github_app_machine_connection_test_support import (_permissions as _permissions)


from datetime import datetime, timezone
from pathlib import Path

import pytest

from yoke_cli.config import github_device_flow
from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import github_machine
from yoke_cli.config import github_machine_state
from yoke_cli.config import writer
from yoke_contracts.machine_config import schema as contract


def _device_opener():
    responses = iter([
        {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {
            "access_token": "access-secret",
            "expires_in": 28_800,
            "refresh_token": "refresh-secret",
            "refresh_token_expires_in": 15_552_000,
        },
    ])
    return lambda request, timeout: _Response(
        next(responses), url=request.full_url,
    )


@pytest.mark.parametrize("target,value", [
    ("user_login", "octocat\x1b]2;spoof"),
    ("account_login", "org\x9b31m"),
    ("account_type", "[bold]Organization"),
    ("app_slug", "x" * 101),
    ("full_name", "octo-org/repo\x07"),
    ("default_branch", "--help"),
    ("default_branch", "main\u202e"),
])
def test_discovery_rejects_hostile_persisted_identity_fields(
    target: str, value: str,
) -> None:
    def opener(request, timeout):
        if request.full_url.endswith("/user"):
            return _Response({
                "id": 42,
                "login": value if target == "user_login" else "octocat",
            }, url=request.full_url)
        if "/user/installations?" in request.full_url:
            return _Response({"installations": [{
                "id": 123,
                "app_id": 123,
                "app_slug": value if target == "app_slug" else "yoke-local",
                "account": {
                    "id": 9,
                    "login": value if target == "account_login" else "octo-org",
                    "type": value if target == "account_type" else "Organization",
                },
                "repository_selection": "selected",
                "permissions": _permissions(),
            }]}, url=request.full_url)
        if "/repositories?" in request.full_url:
            return _Response({"repositories": [{
                "id": 456,
                "full_name": value if target == "full_name" else "octo-org/app",
                "default_branch": value if target == "default_branch" else "main",
                "private": True,
            }]}, url=request.full_url)
        raise AssertionError(request.full_url)

    with pytest.raises(github_app_user_api.GitHubAppUserApiError):
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            web_url="https://github.com",
            access_token="access",
            opener=opener,
        )


def test_config_failure_surfaces_credential_cleanup_failure_without_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    monkeypatch.setattr(
        writer,
        "set_github",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            writer.MachineConfigWriteError("config write failed")
        ),
    )
    monkeypatch.setattr(
        github_machine_state,
        "release_config_credential",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("credential-secret-path")
        ),
    )

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="credential rollback could not complete safely",
    ) as caught:
        github_machine.connect(
            config_path=config,
            client_id="Iv1.local",
            app_slug="yoke-local",
            app_id=123,
            api_url=contract.DEFAULT_GITHUB_API_URL,
            web_url=contract.DEFAULT_GITHUB_WEB_URL,
            device_opener=_device_opener(),
            api_opener=_empty_installation_opener,
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert "credential-secret-path" not in str(caught.value)
    assert not config.exists()


@pytest.mark.parametrize("field", ["expires_in", "refresh_token_expires_in"])
def test_token_document_rejects_boolean_expiry(field: str) -> None:
    payload = {
        "access_token": "access-secret",
        "expires_in": 300,
        "refresh_token": "refresh-secret",
        "refresh_token_expires_in": 600,
    }
    payload[field] = True

    with pytest.raises(
        github_git_credential_store.GitHubCredentialStoreError,
        match="positive integer",
    ):
        github_git_credential_store.credential_document_from_token_response(
            payload,
            now=datetime(2026, 7, 9, tzinfo=timezone.utc),
        )


def test_device_authorization_rejects_boolean_timing() -> None:
    response = {
        "device_code": "device-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": True,
        "interval": 5,
    }

    with pytest.raises(
        github_device_flow.GitHubDeviceFlowError,
        match="timing is invalid",
    ):
        github_device_flow.authorize(
            client_id="Iv1.local",
            web_url="https://github.com",
            opener=lambda request, timeout: _Response(
                response, url=request.full_url,
            ),
        )


def test_connect_rejects_boolean_app_id_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    calls: list[str] = []

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="App id must be a positive integer",
    ):
        github_machine.connect(
            config_path=tmp_path / "home" / "config.json",
            client_id="Iv1.local",
            app_slug="yoke-local",
            app_id=True,
            api_url=contract.DEFAULT_GITHUB_API_URL,
            web_url=contract.DEFAULT_GITHUB_WEB_URL,
            device_opener=lambda request, timeout: calls.append(request.full_url),
        )

    assert calls == []


def test_status_never_reports_authorization_kind_or_credential_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, credential = _configured_machine(
        tmp_path, monkeypatch, auth_kind="legacy-source-kind",
    )

    report = github_machine.status(config_path=config, check=False)
    rendered = github_machine.dumps_json(report)

    assert "kind" not in report["authorization"]
    assert "legacy-source-kind" not in rendered
    assert str(credential) not in rendered
