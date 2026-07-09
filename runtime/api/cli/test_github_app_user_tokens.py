from __future__ import annotations

from datetime import datetime, timezone
import json
import urllib.parse
from typing import Any

import pytest

from yoke_cli.config import github_user_tokens, machine_config
from yoke_contracts.machine_config import schema as contract


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status = 200
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_refresh_from_machine_config_uses_device_flow_without_client_secret(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    refresh_path = tmp_path / "secrets" / "github.user-refresh"
    refresh_path.parent.mkdir()
    refresh_path.write_text("old-refresh\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "app_slug": "yoke-local",
            "client_id": "Iv1.local",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": str(refresh_path),
                "login": "machine-user",
                "status": "authorized",
            },
        },
    }), encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        return _FakeResponse({
            "access_token": "ghu_access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
            "scope": "",
            "token_type": "bearer",
        })

    refreshed = github_user_tokens.refresh_from_machine_config(
        config_path=config_path,
        now=datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc),
        opener=fake_urlopen,
    )

    assert seen["url"] == "https://github.com/login/oauth/access_token"
    assert seen["body"] == {
        "client_id": ["Iv1.local"],
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh"],
    }
    assert "client_secret" not in seen["body"]
    assert refreshed.access_token == "ghu_access"
    assert refreshed.refresh_rotated is True
    assert refreshed.refresh_credential_ref == str(refresh_path)
    assert refresh_path.read_text(encoding="utf-8").strip() == "new-refresh"


def test_refresh_user_access_token_can_include_hosted_client_secret() -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["body"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        return _FakeResponse({
            "access_token": "ghu_access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
        })

    refreshed = github_user_tokens.refresh_user_access_token(
        client_id="Iv1.hosted",
        client_secret="hosted-secret",
        refresh_token="refresh",
        now=datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc),
        opener=fake_urlopen,
    )

    assert seen["body"]["client_secret"] == ["hosted-secret"]
    assert refreshed.refresh_token == "new-refresh"


def test_refresh_from_machine_config_rejects_pending_authorization(tmp_path) -> None:
    refresh_path = tmp_path / "github.user-refresh"
    refresh_path.write_text("old-refresh\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "app_slug": "yoke-local",
            "client_id": "Iv1.local",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": str(refresh_path),
                "status": "pending",
            },
        },
    }), encoding="utf-8")

    with pytest.raises(github_user_tokens.GitHubUserTokenError, match="not authorized"):
        github_user_tokens.refresh_from_machine_config(config_path=config_path)
