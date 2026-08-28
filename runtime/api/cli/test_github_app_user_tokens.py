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

from .github_user_token_test_support import (
    NOW,
    FakeResponse,
    configured_credential,
)


def test_credential_read_rejects_group_readable_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = configured_credential(
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
    config_path, credential_path = configured_credential(
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
    config_path, credential_path = configured_credential(
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
    config_path, _credential_path = configured_credential(
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
            opener=lambda request, timeout: FakeResponse({
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
        return FakeResponse({
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
