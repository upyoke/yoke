from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import urllib.error

import pytest

from yoke_cli.config import github_device_flow
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import github_machine
from yoke_cli.config import github_machine_state
from yoke_cli.config import writer
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


def _permissions() -> dict[str, str]:
    return {
        item.key: item.access
        for item in (
            github_app_installation_permissions
            .REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
        )
    }


def _configured_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_kind: str = contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
    credential_ref: Path | None = None,
) -> tuple[Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    credential = (
        credential_ref
        or home / "secrets" / f"github-app-user-{'a' * 32}.json"
    )
    if credential_ref is None:
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
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            "app_slug": "yoke-local",
            "client_id": "Iv1.local",
            "authorization": {
                "kind": auth_kind,
                "refresh_credential_ref": str(credential),
                "status": "authorized",
                "github_user_id": 42,
                "login": "octocat",
            },
            "installations": [{
                "installation_id": 123,
                "account_id": 9,
                "account_login": "octo-org",
                "account_type": "Organization",
                "repository_selection": "selected",
                "suspended": False,
                "permissions": _permissions(),
            }],
            "repositories": [{
                "repository_id": 456,
                "installation_id": 123,
                "full_name": "octo-org/app",
                "default_branch": "main",
            }],
        },
    }), encoding="utf-8")
    return config, credential


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
    return lambda request, timeout: _Response(next(responses))


def _empty_installation_opener(request, timeout):
    if request.full_url.endswith("/user"):
        return _Response({"id": 42, "login": "octocat"})
    if "/user/installations?" in request.full_url:
        return _Response({"installations": []})
    raise AssertionError(request.full_url)


def test_status_marks_live_failure_as_cached_and_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    report = github_machine.status(config_path=config, api_opener=unavailable)

    assert report["ok"] is False
    assert report["ready"] is False
    assert report["identity"]["checked"] is True
    assert report["identity"]["ok"] is False
    assert report["access"]["snapshot_source"] == "cached"
    assert report["access"]["repo_listing_ok"] is False
    assert report["access"]["org_listing_ok"] is False


def test_revoked_status_reports_config_persistence_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)

    def revoked(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", hdrs=None, fp=None,
        )

    monkeypatch.setattr(
        writer,
        "set_github",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            writer.MachineConfigWriteError("read-only config")
        ),
    )

    report = github_machine.status(config_path=config, api_opener=revoked)

    codes = {item["code"] for item in report["issues"]}
    assert "github_revoked_status_not_persisted" in codes
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["github"]["authorization"]["status"] == "authorized"


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
        "remove_owned_credential",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("credential-secret-path")
        ),
    )

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="could not be cleaned up safely",
    ) as caught:
        github_machine.connect(
            config_path=config,
            client_id="Iv1.local",
            app_slug="yoke-local",
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
            opener=lambda request, timeout: _Response(response),
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


def test_disconnect_sanitizes_outside_secrets_credential_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside" / "credential.json"
    config, _credential = _configured_machine(
        tmp_path, monkeypatch, credential_ref=outside,
    )

    report = github_machine.disconnect(config_path=config)
    rendered = github_machine.dumps_json(report)

    assert report["ok"] is False
    assert report["issues"][0]["code"] == "github_credential_not_removed"
    assert str(outside) not in rendered


def test_disconnect_sanitizes_unlink_failure_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, credential = _configured_machine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        github_git_credential_file,
        "delete_json_document",
        lambda path: (_ for _ in ()).throw(
            github_git_credential_file.CredentialFileError(
                f"unlink failed for {credential}"
            )
        ),
    )

    report = github_machine.disconnect(config_path=config)
    rendered = github_machine.dumps_json(report)

    assert report["ok"] is False
    assert report["issues"][0]["code"] == "github_credential_not_removed"
    assert str(credential) not in rendered


def test_suspended_installation_is_not_misreported_as_missing_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["github"]["installations"][0]["suspended"] = True
    config.write_text(json.dumps(payload), encoding="utf-8")

    report = github_machine.status(config_path=config, check=False)
    codes = {item["code"] for item in report["issues"]}

    assert report["permissions"]["ok"] is True
    assert report["permissions"]["usable"] is False
    assert report["ready"] is False
    assert "github_app_installation_suspended" in codes
    assert "github_app_no_usable_installation" in codes
    assert "github_app_installation_permissions_incomplete" not in codes
