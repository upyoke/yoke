"""Storage and transport limits for GitHub App user-token documents."""

from __future__ import annotations

from datetime import timedelta
import json
import urllib.error

import pytest

from runtime.api.cli.test_github_app_user_tokens import (
    NOW,
    _FakeResponse,
    _RawResponse,
    _configured_credential,
)
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_git_credential_document as credential_document
from yoke_cli.config import github_git_credential_store as credential_store
from yoke_cli.config import github_user_tokens, machine_config


def test_explicit_config_outside_default_home_uses_default_secret_authority(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(machine_config.HOME_ENV, raising=False)
    home = tmp_path / "default-home"
    original_config, credential = _configured_credential(
        home, expires_at=NOW + timedelta(hours=1),
    )
    config = tmp_path / "operator-config" / "config.json"
    config.parent.mkdir()
    config.write_bytes(original_config.read_bytes())
    config.chmod(0o600)
    monkeypatch.setattr(
        credential_document, "_default_machine_home", lambda: home,
    )

    token = github_user_tokens.access_token_from_machine_config(
        config_path=config,
        now=NOW,
        opener=lambda request, timeout: _FakeResponse({
            "access_token": "new-access",
            "expires_in": 28_800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15_552_000,
        }),
    )

    assert token.refresh_credential_ref == str(credential)


def test_refresh_ref_cannot_target_an_operator_managed_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1),
    )
    external = (
        tmp_path / "operator-secrets" / f"github-app-user-{'b' * 32}.json"
    )
    credential_store.write_credential_document(external, {
        "schema_version": 2,
        "refresh_token": "operator-refresh",
        "refresh_expires_at": (NOW + timedelta(days=30)).isoformat(),
    })
    before = external.read_bytes()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["github"]["authorization"]["refresh_credential_ref"] = str(external)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    oauth_calls: list[str] = []

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError, match="not Yoke-owned",
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
            now=NOW,
            opener=lambda request, timeout: oauth_calls.append(request.full_url),
        )

    assert oauth_calls == []
    assert external.read_bytes() == before


def test_initial_credential_storage_requires_completed_device_flow(tmp_path) -> None:
    target = tmp_path / "secrets" / f"github-app-user-{'a' * 32}.json"
    token_response = {
        "access_token": "access-secret", "expires_in": 28_800,
        "refresh_token": "refresh-secret",
        "refresh_token_expires_in": 15_552_000,
    }
    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="only after device flow",
    ):
        github_user_tokens.store_initial_token(target, token_response)
    assert not target.exists()


def test_credential_read_rejects_oversize_document_without_echoing_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    marker = b"credential-body-must-not-leak"
    credential_path.write_bytes(
        marker + b"x" * credential_file.MAX_CREDENTIAL_DOCUMENT_BYTES
    )
    credential_path.chmod(0o600)
    with pytest.raises(
        github_user_tokens.GitHubUserTokenError, match="document is too large"
    ) as caught:
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path, now=NOW,
        )
    assert marker.decode("ascii") not in str(caught.value)


def test_credential_read_rejects_invalid_utf8_without_echoing_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    credential_path.write_bytes(b"credential-body-must-not-leak-\xff")
    credential_path.chmod(0o600)
    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="not a credential document",
    ) as caught:
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path, now=NOW,
        )
    assert "credential-body-must-not-leak" not in str(caught.value)


def test_refresh_invalid_utf8_is_a_typed_response_error() -> None:
    with pytest.raises(
        github_user_tokens.GitHubUserTokenResponseError, match="not JSON",
    ):
        github_user_tokens.refresh_user_access_token(
            client_id="Iv1.hosted", refresh_token="refresh-secret", now=NOW,
            opener=lambda request, timeout: _RawResponse(b"\xff"),
        )


def test_refresh_transport_reason_redacts_submitted_refresh_secret() -> None:
    with pytest.raises(
        github_user_tokens.GitHubUserTokenResponseError,
    ) as caught:
        github_user_tokens.refresh_user_access_token(
            client_id="Iv1.hosted", refresh_token="refresh-secret", now=NOW,
            opener=lambda request, timeout: (_ for _ in ()).throw(
                urllib.error.URLError("refused refresh-secret")
            ),
        )
    assert "refresh-secret" not in str(caught.value)
    assert "could not be reached" in str(caught.value)


@pytest.mark.parametrize("failure", [
    TimeoutError("socket detail must not leak"),
    OSError("platform detail must not leak"),
])
def test_refresh_wraps_direct_transport_errors_without_details(
    failure: Exception,
) -> None:
    with pytest.raises(
        github_user_tokens.GitHubUserTokenResponseError,
    ) as caught:
        github_user_tokens.refresh_user_access_token(
            client_id="Iv1.hosted", refresh_token="refresh-secret", now=NOW,
            opener=lambda request, timeout: (_ for _ in ()).throw(failure),
        )
    assert "could not be reached" in str(caught.value)
    assert "must not leak" not in str(caught.value)


@pytest.mark.parametrize("field,value", [
    ("expires_in", 86_401),
    ("refresh_token_expires_in", 31_622_401),
    ("refresh_token_expires_in", 10**100),
])
def test_refresh_rejects_unbounded_token_timing(
    field: str, value: int,
) -> None:
    payload = {
        "access_token": "new-access", "expires_in": 28_800,
        "refresh_token": "new-refresh",
        "refresh_token_expires_in": 15_552_000,
        field: value,
    }
    with pytest.raises(
        github_user_tokens.GitHubUserTokenResponseError,
        match="positive integer",
    ):
        github_user_tokens.refresh_user_access_token(
            client_id="Iv1.hosted", refresh_token="refresh-secret", now=NOW,
            opener=lambda request, timeout: _FakeResponse(payload),
        )
