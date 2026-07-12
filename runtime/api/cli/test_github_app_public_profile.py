"""Public GitHub App profile discovery and profile-bound token guards."""

from __future__ import annotations

import json
from typing import Any

import pytest

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_binding_auth
from yoke_contracts import github_app_public


class _Response:
    def __init__(self, payload: Any, *, url: str) -> None:
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body[:size] if size >= 0 else self.body

    def geturl(self) -> str:
        return self.url


def _advertisement(**overrides: Any) -> dict[str, Any]:
    return {
        "available": True,
        "client_id": "Iv1.product",
        "app_slug": "yoke-product",
        "app_id": 123,
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
        **overrides,
    }


def _bundled_profile(values: dict[str, Any]):
    return github_app_public_profile.github_app_tokens.LocalProductGitHubAppProfile(
        **{
            key: value for key, value in values.items()
            if key != "available"
        }
    )


def _clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        github_app_public.GITHUB_APP_CLIENT_ID_ENV,
        github_app_public.GITHUB_APP_SLUG_ENV,
        github_app_public.GITHUB_APP_ID_ENV,
        github_app_public.GITHUB_APP_API_URL_ENV,
        github_app_public.GITHUB_APP_WEB_URL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def test_health_discovery_is_direct_credential_free_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    seen: dict[str, Any] = {}

    def opener(request, timeout):
        seen.update(
            url=request.full_url,
            authorization=request.headers.get("Authorization"),
            method=request.get_method(),
        )
        return _Response(
            {"github_app": _advertisement()},
            url=request.full_url,
        )

    profile = github_app_public_profile.resolve(
        service_api_url="https://api.stage.upyoke.com",
        opener=opener,
    )

    assert github_app_public_profile.as_metadata(profile) == {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    assert seen == {
        "url": "https://api.stage.upyoke.com/v1/health",
        "authorization": None,
        "method": "GET",
    }


def test_old_web_env_name_is_not_a_partial_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("YOKE_GITHUB_WEB_URL", "https://legacy.invalid")
    calls: list[str] = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return _Response(
            {"github_app": _advertisement()}, url=request.full_url
        )

    profile = github_app_public_profile.resolve(
        service_api_url="https://api.upyoke.com", opener=opener,
    )

    assert profile.web_url == "https://github.com"
    assert calls == ["https://api.upyoke.com/v1/health"]


def test_partial_canonical_env_fails_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv(
        github_app_public.GITHUB_APP_CLIENT_ID_ENV, "Iv1.partial"
    )
    calls: list[str] = []

    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="complete profile",
    ):
        github_app_public_profile.resolve(
            service_api_url="https://api.upyoke.com",
            opener=lambda request, timeout: calls.append(request.full_url),
        )

    assert calls == []


def test_public_profile_rejects_boolean_app_id() -> None:
    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="App id must be a positive integer",
    ):
        github_app_public_profile.resolve(
            service_api_url=None,
            client_id="Iv1.local",
            app_slug="yoke-local",
            app_id=True,
            api_url="https://api.github.com",
            web_url="https://github.com",
        )


def test_unavailable_or_redirected_health_is_not_an_app_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)

    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="unavailable",
    ):
        github_app_public_profile.fetch(
            "https://api.upyoke.com",
            opener=lambda request, timeout: _Response(
                {}, url=request.full_url
            ),
        )
    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="redirected",
    ):
        github_app_public_profile.fetch(
            "https://api.upyoke.com",
            opener=lambda request, timeout: _Response(
                {"github_app": _advertisement()},
                url="https://redirected.example/v1/health",
            ),
        )


def test_health_discovery_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="too large",
    ):
        github_app_public_profile.fetch(
            "https://api.upyoke.com",
            opener=lambda request, timeout: _Response(
                b"x" * (64 * 1024 + 1), url=request.full_url
            ),
        )


def test_binding_profile_mismatch_prevents_token_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    saved["app_id"] = 999
    saved.update({
        "profile_source": "service",
        "profile_service_api_url": "https://api.upyoke.com",
    })
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: saved,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "active_connection",
        lambda _path=None: {
            "transport": "https",
            "api_url": "https://api.upyoke.com",
        },
    )
    token_calls: list[str] = []

    def profile_opener(request, timeout):
        return _Response(
            {"github_app": _advertisement()}, url=request.full_url
        )

    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        lambda **kwargs: token_calls.append("token"),
    )
    with pytest.raises(
        github_binding_auth.GitHubBindingAuthError,
        match="different Yoke GitHub App profile",
    ):
        github_binding_auth.access_token_for_binding(
            profile_opener=profile_opener,
        )

    assert token_calls == []


def test_local_binding_validates_saved_profile_without_remote_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    saved["profile_source"] = "local_explicit"
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: saved,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "active_connection",
        lambda _path=None: {"transport": "local-postgres", "env": "local"},
    )
    expected = object()
    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        lambda **kwargs: expected,
    )

    result = github_binding_auth.access_token_for_binding(
        profile_opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local binding must not fetch hosted health")
        ),
    )

    assert result is expected


@pytest.mark.parametrize(
    "service_url",
    ["https://api.upyoke.com", "https://yoke.team.example"],
)
def test_https_binding_uses_exact_selected_service_before_token(
    monkeypatch: pytest.MonkeyPatch,
    service_url: str,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    saved.update({
        "profile_source": "service",
        "profile_service_api_url": service_url,
    })
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: saved,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "active_connection",
        lambda _path=None: {"transport": "https", "api_url": service_url},
    )
    order: list[str] = []

    def opener(request, timeout):
        order.append(request.full_url)
        return _Response(
            {"github_app": _advertisement()}, url=request.full_url
        )

    expected = object()
    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        lambda **kwargs: order.append("token") or expected,
    )

    assert github_binding_auth.access_token_for_binding(
        profile_opener=opener,
    ) is expected
    assert order == [f"{service_url}/v1/health", "token"]
