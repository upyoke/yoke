"""Public GitHub App profile, attestation, and health-wire contracts."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.api.domain.github_app_public_profile_test_support import (
    complete_github_app_env as _complete_env,
)
from yoke_contracts.github_app_public import (
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
    GitHubAppPublicProfile,
    parse_github_app_advertisement,
)
import yoke_core.api.main as _api_main  # noqa: F401
from yoke_core.api.routes import items_health
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_PRIVATE_KEY_MAX_BYTES,
    GitHubAppControlPlaneConfigError,
    github_app_public_advertisement,
    load_github_app_control_plane_config,
    load_github_app_public_profile,
)
from yoke_core.domain.github_app_identity import GitHubAppIdentity
from yoke_core.domain.github_app_public_runtime import (
    attest_github_app_runtime_identity,
    current_github_app_public_advertisement,
    reset_github_app_public_attestation_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_attestation():
    reset_github_app_public_attestation_for_tests()
    yield
    reset_github_app_public_attestation_for_tests()


def _private_only_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    env, key = _complete_env(tmp_path)
    for name in (
        GITHUB_APP_WEB_URL_ENV,
        GITHUB_APP_ID_ENV,
        GITHUB_APP_CLIENT_ID_ENV,
        GITHUB_APP_SLUG_ENV,
    ):
        env.pop(name)
    return env, key


def test_advertisement_contract_has_exact_unavailable_and_complete_variants():
    unavailable = parse_github_app_advertisement({"available": False})
    assert unavailable.model_dump() == {"available": False}

    profile = parse_github_app_advertisement(
        {
            "available": True,
            "client_id": "Iv23public",
            "app_slug": "yoke-development",
            "app_id": 123456,
            "api_url": "https://api.github.com/",
            "web_url": "https://github.com/",
        }
    )
    assert isinstance(profile, GitHubAppPublicProfile)
    assert profile.api_url == "https://api.github.com"
    assert profile.web_url == "https://github.com"

    with pytest.raises(ValidationError):
        parse_github_app_advertisement(
            {
                "available": False,
                "issuer": "must-not-leak",
            }
        )


def test_partial_self_host_profile_is_detail_free_unavailable(tmp_path: Path):
    env, _key = _complete_env(tmp_path)
    env.pop(GITHUB_APP_SLUG_ENV)

    assert github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }
    with pytest.raises(
        GitHubAppControlPlaneConfigError,
        match="profile is incomplete",
    ):
        load_github_app_public_profile(env, strict_partial=True)


@pytest.mark.parametrize("profile_break", ["partial", "invalid"])
def test_partial_or_invalid_profile_warns_without_values(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    profile_break: str,
):
    env, _key = _complete_env(tmp_path)
    if profile_break == "partial":
        env.pop(GITHUB_APP_SLUG_ENV)
    else:
        env[GITHUB_APP_WEB_URL_ENV] = "https://unrelated.example"
    identity = GitHubAppIdentity(
        app_id=123456,
        client_id="Iv23public",
        slug="yoke-development",
    )

    with caplog.at_level(logging.WARNING, logger="yoke.api.startup"):
        assert attest_github_app_runtime_identity(
            env,
            identity_fetcher=lambda *args, **kwargs: identity,
        )

    assert "set every public profile field" in caplog.text
    assert "Iv23public" not in caplog.text
    assert "unrelated.example" not in caplog.text
    assert "test-private-key" not in caplog.text
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


def test_unreadable_key_cannot_advertise_available(tmp_path: Path):
    env, key = _complete_env(tmp_path)
    key.chmod(0o644)

    assert github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


def test_partial_profile_warning_survives_private_key_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    env, key = _complete_env(tmp_path)
    env.pop(GITHUB_APP_SLUG_ENV)
    key.chmod(0o644)

    with caplog.at_level(logging.WARNING, logger="yoke.api.startup"):
        assert not attest_github_app_runtime_identity(env)

    assert "set every public profile field" in caplog.text
    assert "startup continued without verified App authority" in caplog.text
    assert "Iv23public" not in caplog.text
    assert "test-private-key" not in caplog.text


def test_control_plane_private_key_read_is_size_bounded(tmp_path: Path):
    env, key = _complete_env(tmp_path)
    key.write_bytes(b"x" * (GITHUB_APP_PRIVATE_KEY_MAX_BYTES + 1))
    key.chmod(0o600)

    with pytest.raises(GitHubAppControlPlaneConfigError, match="size limit"):
        load_github_app_control_plane_config(env)


def test_startup_attestation_binds_health_to_identity_and_key(tmp_path: Path):
    env, key = _complete_env(tmp_path)
    identity = GitHubAppIdentity(
        app_id=123456,
        client_id="Iv23public",
        slug="yoke-development",
    )
    seen = []

    def fetch(config, *, opener, timeout_seconds):
        seen.append((config.endpoint.base_url, opener, timeout_seconds))
        return identity

    assert (
        attest_github_app_runtime_identity(
            env,
            identity_fetcher=fetch,
            timeout_seconds=4.5,
        )
        is True
    )
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": True,
        "client_id": "Iv23public",
        "app_slug": "yoke-development",
        "app_id": 123456,
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
    }
    assert seen == [("https://api.github.com", None, 4.5)]

    key.write_text("rotated-unattested-key", encoding="utf-8")
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


def test_private_only_runtime_identity_is_attested_without_advertisement(
    tmp_path: Path,
):
    env, _key = _private_only_env(tmp_path)
    identity = GitHubAppIdentity(
        app_id=123456,
        client_id="Iv23public",
        slug="yoke-development",
    )
    seen = []

    def fetch(config, *, opener, timeout_seconds):
        seen.append((config.issuer, opener, timeout_seconds))
        return identity

    assert attest_github_app_runtime_identity(
        env,
        identity_fetcher=fetch,
        timeout_seconds=3.0,
    )
    assert seen == [("123456", None, 3.0)]
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


def test_private_only_unreadable_key_fails_before_identity_request(tmp_path: Path):
    env, key = _private_only_env(tmp_path)
    key.chmod(0o644)
    identity_requested = False

    def fetch(*args, **kwargs):
        nonlocal identity_requested
        identity_requested = True
        raise AssertionError("identity request must not use an unsafe key")

    assert not attest_github_app_runtime_identity(env, identity_fetcher=fetch)
    assert identity_requested is False


def test_private_only_bad_identity_is_not_retried_until_restart(tmp_path: Path):
    env, _key = _private_only_env(tmp_path)
    calls = []

    def bad_identity(*args, **kwargs):
        calls.append("bad")
        raise RuntimeError("provider detail must not escape")

    assert not attest_github_app_runtime_identity(
        env,
        identity_fetcher=bad_identity,
    )
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }
    assert calls == ["bad"]

    identity = GitHubAppIdentity(
        app_id=123456,
        client_id="Iv23public",
        slug="yoke-development",
    )
    reset_github_app_public_attestation_for_tests()
    assert attest_github_app_runtime_identity(
        env,
        identity_fetcher=lambda *args, **kwargs: identity,
    )


def test_startup_timeout_logs_no_failure_detail(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    env, _key = _complete_env(tmp_path)

    def timeout(*args, **kwargs):
        raise TimeoutError("sensitive provider response detail")

    with caplog.at_level(logging.WARNING, logger="yoke.api.startup"):
        assert (
            attest_github_app_runtime_identity(
                env,
                identity_fetcher=timeout,
                timeout_seconds=0.01,
            )
            is False
        )
    assert "startup continued without verified App authority" in caplog.text
    assert "sensitive provider response detail" not in caplog.text
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


def test_health_wire_embeds_only_the_typed_advertisement(monkeypatch):
    profile = GitHubAppPublicProfile(
        client_id="Iv23public",
        app_slug="yoke-development",
        app_id=123456,
        api_url="https://api.github.com",
        web_url="https://github.com",
    )
    monkeypatch.setattr(
        items_health,
        "current_github_app_public_advertisement",
        lambda: profile,
    )
    monkeypatch.setattr(
        items_health,
        "_schema_readiness_snapshot",
        lambda: (True, []),
    )

    payload = items_health.health().model_dump(mode="json")

    assert payload["github_app"] == profile.model_dump(mode="json")
    assert not {
        "issuer",
        "private_key",
        "secret",
        "installation_id",
        "error",
    }.intersection(payload["github_app"])
