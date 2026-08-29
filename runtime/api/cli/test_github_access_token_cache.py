"""The stored access token a git command reuses instead of minting its own."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import stat
from typing import Any
import urllib.parse

import pytest

from yoke_cli.config import github_user_tokens, machine_config
from yoke_cli.config import github_git_credential_store as credential_store
from yoke_contracts import github_app_tokens as token_contract

from .github_user_token_test_support import (
    NOW,
    FakeResponse,
    configured_credential,
)


def test_stored_access_token_is_served_without_rotating_the_authorization(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    before = credential_path.read_text(encoding="utf-8")

    def refuse(request, timeout):
        raise AssertionError("a still-valid access token must not be refreshed")

    token = github_user_tokens.access_token_from_machine_config(
        config_path=config_path, now=NOW, opener=refuse
    )

    assert token.access_token == "stored-access"
    assert token.cached is True
    assert token.refresh_rotated is False
    assert token.refresh_credential_ref == str(credential_path)
    assert "stored-access" not in repr(token)
    assert credential_path.read_text(encoding="utf-8") == before


def test_access_token_inside_the_refresh_margin_is_renewed(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    margin = token_contract.GITHUB_APP_USER_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS
    config_path, _credential_path = configured_credential(
        tmp_path, expires_at=NOW + timedelta(seconds=margin - 1)
    )

    token = github_user_tokens.access_token_from_machine_config(
        config_path=config_path,
        now=NOW,
        opener=lambda request, timeout: FakeResponse({
            "access_token": "new-access",
            "expires_in": 28800,
            "refresh_token": "new-refresh",
            "refresh_token_expires_in": 15552000,
        }),
    )

    assert token.access_token == "new-access"
    assert token.cached is False


def test_renewed_access_token_is_persisted_beside_the_refresh_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = configured_credential(
        tmp_path, expires_at=NOW - timedelta(seconds=1)
    )
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["body"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        return FakeResponse({
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
    assert stored == {
        "schema_version": 2,
        "refresh_token": "new-refresh",
        "refresh_expires_at": (NOW + timedelta(days=180)).isoformat(),
        "config_owners": [],
        "config_ownership_complete": False,
        "cached_access": {
            "access_token": "new-access",
            "expires_at": (NOW + timedelta(hours=8)).isoformat(),
            "scope": "",
            "token_type": "bearer",
        },
    }
    assert stat.S_IMODE(credential_path.stat().st_mode) == 0o600


def test_concurrent_callers_share_one_token_instead_of_revoking_each_other(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race this cache exists to close.

    Two commands starting at once used to each mint a token and revoke the
    other's, so a push failed with a credential prompt on a busy machine and
    succeeded on a quiet one. One refresh now serves both.
    """

    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = configured_credential(
        tmp_path, expires_at=NOW, access_token=None
    )
    submitted_refresh_tokens: list[str] = []

    def fake_urlopen(request, timeout):
        submitted_refresh_tokens.append(
            urllib.parse.parse_qs(request.data.decode("utf-8"))[
                "refresh_token"
            ][0]
        )
        return FakeResponse({
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

    assert submitted_refresh_tokens == ["old-refresh"]
    assert [token.access_token for token in tokens] == [
        "new-access", "new-access",
    ]
    assert sorted(token.cached for token in tokens) == [False, True]


def test_claiming_a_config_owner_does_not_evict_the_cached_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ownership write is not a cache eviction.

    A writer that dropped the access half would send the next git command
    back to minting its own token, which is the race this cache closes.
    """

    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )

    credential_store.claim_config_owner(credential_path, config_path)

    stored = json.loads(credential_path.read_text(encoding="utf-8"))
    assert stored["cached_access"]["access_token"] == "stored-access"
    assert stored["cached_access"]["expires_at"] == (
        NOW + timedelta(hours=1)
    ).isoformat()
    assert stored["config_owners"] == [str(Path(config_path).resolve())]


def test_the_first_token_from_the_device_flow_is_stored_for_reuse() -> None:
    document = credential_store.credential_document_from_token_response(
        {
            "access_token": "first-access",
            "expires_in": 28800,
            "refresh_token": "first-refresh",
            "refresh_token_expires_in": 15552000,
        },
        now=NOW,
    )

    assert document["cached_access"]["access_token"] == "first-access"
    assert document["cached_access"]["expires_at"] == (
        NOW + timedelta(hours=8)
    ).isoformat()


# The exact key names a build shipped before this cache existed refuses at the
# top level of a credential document.
KEYS_AN_OLDER_BUILD_REFUSES = ("access_token", "expires_at", "scope", "token_type")


def test_the_document_stays_readable_by_a_build_without_the_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine runs many Yoke processes, and they upgrade at different times.

    A build that predates the cache refuses a document carrying those names at
    the top level, and the recovery it names is a reconnect — which revokes the
    token every other live process holds. Nesting the cache keeps that build
    reading the document and refreshing exactly as it did before.
    """

    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, credential_path = configured_credential(
        tmp_path, expires_at=NOW - timedelta(seconds=1)
    )

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

    stored = json.loads(credential_path.read_text(encoding="utf-8"))
    assert not set(KEYS_AN_OLDER_BUILD_REFUSES) & set(stored)
    assert stored["cached_access"]["access_token"] == "new-access"
