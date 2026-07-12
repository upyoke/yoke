from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import stat
import urllib.parse
from typing import Any

import pytest

from yoke_cli.config import github_user_tokens, machine_config
from yoke_cli.config import github_git_credential_store as credential_store
from yoke_contracts.machine_config import schema as contract


class _FakeResponse:
    def __init__(
        self,
        body: dict[str, Any],
        *,
        url: str = "https://github.com/login/oauth/access_token",
    ) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body[:size] if size >= 0 else self._body

    def geturl(self) -> str:
        return self.url


class _RawResponse(_FakeResponse):
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.url = "https://github.com/login/oauth/access_token"


NOW = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)


def _configured_credential(tmp_path, *, expires_at: datetime) -> tuple[Any, Any]:
    credential_path = (
        tmp_path / "secrets" / f"github-app-user-{'a' * 32}.json"
    )
    credential_store.write_credential_document(credential_path, {
        "schema_version": 2,
        "refresh_token": "old-refresh",
        "refresh_expires_at": (NOW + timedelta(days=30)).isoformat(),
    })
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "active_env": "local",
        "connections": {
            "local": {"transport": "local-postgres", "prod": False},
        },
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            "app_slug": "yoke-local",
            "app_id": 123,
            "client_id": "Iv1.local",
            "profile_source": "local_explicit",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": str(credential_path),
                "login": "machine-user",
                "status": "authorized",
            },
        },
    }), encoding="utf-8")
    config_path.chmod(0o600)
    return config_path, credential_path


def test_access_token_always_refreshes_and_never_persists_access_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )

    def fake_urlopen(request, timeout):
        return _FakeResponse({
            "access_token": "new-access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
        })

    token = github_user_tokens.access_token_from_machine_config(
        config_path=config_path, now=NOW, opener=fake_urlopen
    )

    assert token.access_token == "new-access"
    assert token.cached is False
    assert token.refresh_rotated is True
    assert token.refresh_credential_ref == str(credential_path)
    assert "new-access" not in repr(token)
    assert "new-refresh" not in repr(token)
    stored = json.loads(credential_path.read_text(encoding="utf-8"))
    assert stored == {
        "schema_version": 2,
        "refresh_token": "new-refresh",
        "refresh_expires_at": (NOW + timedelta(days=180)).isoformat(),
        "config_owners": [],
        "config_ownership_complete": False,
    }


def test_expired_access_token_rotates_one_atomic_document(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW - timedelta(seconds=1)
    )
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["body"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        return _FakeResponse({
            "access_token": "new-access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
            "token_type": "bearer",
        })

    token = github_user_tokens.access_token_from_machine_config(
        config_path=config_path, now=NOW, opener=fake_urlopen
    )

    assert seen["body"] == {
        "client_id": ["Iv1.local"],
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh"],
    }
    assert token.access_token == "new-access"
    assert token.cached is False
    assert token.refresh_rotated is True
    stored = json.loads(credential_path.read_text(encoding="utf-8"))
    assert "access_token" not in stored
    assert "expires_at" not in stored
    assert stored["refresh_token"] == "new-refresh"
    assert stat.S_IMODE(credential_path.stat().st_mode) == 0o600


def test_concurrent_callers_each_refresh_under_one_lock(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW - timedelta(seconds=1)
    )
    calls = 0
    submitted_refresh_tokens: list[str] = []

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        submitted_refresh_tokens.append(
            urllib.parse.parse_qs(request.data.decode("utf-8"))[
                "refresh_token"
            ][0]
        )
        return _FakeResponse({
            "access_token": "new-access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
        })

    def get_token():
        return github_user_tokens.access_token_from_machine_config(
            config_path=config_path, now=NOW, opener=fake_urlopen
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _index: get_token(), range(2)))

    assert calls == 2
    assert submitted_refresh_tokens == ["old-refresh", "new-refresh"]
    assert [token.access_token for token in tokens] == [
        "new-access", "new-access",
    ]
    assert [token.cached for token in tokens] == [False, False]


def test_credential_read_rejects_group_readable_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    credential_path.chmod(0o640)

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError, match="permissions must be 0600"
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path, now=NOW
        )


def test_credential_read_rejects_group_accessible_parent(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    credential_path.parent.chmod(0o750)

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="operation lock is unavailable",
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path, now=NOW
        )


def test_expired_refresh_credential_routes_to_device_reconnect(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW - timedelta(hours=1)
    )
    document = json.loads(credential_path.read_text(encoding="utf-8"))
    document["refresh_expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    credential_store.write_credential_document(credential_path, document)

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="yoke github connect",
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
            now=NOW,
            opener=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("expired refresh tokens must not be sent")
            ),
        )


def test_rotated_refresh_local_save_failure_requires_reconnect(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW - timedelta(seconds=1)
    )
    monkeypatch.setattr(
        credential_store,
        "write_credential_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            credential_store.GitHubCredentialStoreError("disk full")
        ),
    )

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="rotated.*yoke github connect",
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
            now=NOW,
            opener=lambda request, timeout: _FakeResponse({
                "access_token": "new-access",
                "expires_in": 28800,
                "refresh_token": "new-refresh",
                "refresh_token_expires_in": 15552000,
            }),
        )


def test_direct_refresh_can_include_hosted_client_secret() -> None:
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
        client_id="Iv1.hosted", client_secret="hosted-secret",
        refresh_token="refresh", now=NOW, opener=fake_urlopen,
    )

    assert seen["body"]["client_secret"] == ["hosted-secret"]
    assert refreshed.refresh_token == "new-refresh"


def test_oversized_persisted_refresh_document_is_rejected_before_replace(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    credential_path = (
        tmp_path / "secrets" / f"github-app-user-{'b' * 32}.json"
    )
    oversized_refresh = "r" * (64 * 1024 - 100)

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="document is too large",
    ):
        github_user_tokens.store_initial_token(
            credential_path,
            {
                "access_token": "access",
                "expires_in": 28800,
                "refresh_token": oversized_refresh,
                "refresh_token_expires_in": 15552000,
            },
            device_flow_completed=True,
        )

    assert not credential_path.exists()
