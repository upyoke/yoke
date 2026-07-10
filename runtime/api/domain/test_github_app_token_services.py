from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from yoke_core.domain import github_app_installation_tokens as installation_tokens
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_token_models import GitHubAppTokenError


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status = 201
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._body


def _private_key_pair() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _token_payload(token: str, public_pem: bytes) -> dict[str, Any]:
    return jwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )


def test_app_jwt_uses_github_claim_window() -> None:
    private_pem, public_pem = _private_key_pair()
    now = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)

    encoded = generate_app_jwt(
        issuer="Iv1.client",
        private_key_pem=private_pem,
        now=now,
    )

    claims = _token_payload(encoded, public_pem)
    assert claims["iss"] == "Iv1.client"
    assert claims["iat"] == int((now - timedelta(seconds=60)).timestamp())
    assert claims["exp"] == int((now + timedelta(seconds=600)).timestamp())


def test_mint_installation_token_posts_jwt_and_restrictions() -> None:
    private_pem, public_pem = _private_key_pair()
    now = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({
            "token": "ghs_install",
            "expires_at": "2026-07-09T18:00:00Z",
            "permissions": {"issues": "write"},
            "repository_selection": "selected",
            "repositories": [{"full_name": "octo/repo"}],
        })

    token = installation_tokens.mint_installation_token(
        issuer=12345,
        private_key_pem=private_pem,
        installation_id=99,
        repository_ids=[1001],
        permissions={"issues": "write"},
        now=now,
        opener=fake_urlopen,
    )

    assert seen["url"] == (
        "https://api.github.com/app/installations/99/access_tokens"
    )
    assert seen["method"] == "POST"
    assert seen["body"] == {
        "repository_ids": [1001],
        "permissions": {"issues": "write"},
    }
    headers = {key.lower(): value for key, value in seen["headers"].items()}
    claims = _token_payload(headers["authorization"].removeprefix("Bearer "), public_pem)
    assert claims["iss"] == "12345"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert token.token == "ghs_install"
    assert token.expires_at == datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc)
    assert token.permissions == {"issues": "write"}
    assert token.repository_selection == "selected"
    assert token.repositories == ("octo/repo",)
    assert "ghs_install" not in repr(token)


def test_installation_token_cache_reuses_token_until_expiry() -> None:
    private_pem, _public_pem = _private_key_pair()
    now = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return _FakeResponse({
            "token": f"ghs_{len(calls)}",
            "expires_at": "2026-07-09T17:10:00Z",
        })

    cache = installation_tokens.InstallationTokenCache()

    first = cache.get_or_mint(
        issuer="Iv1.client",
        private_key_pem=private_pem,
        installation_id=7,
        repositories=["repo"],
        now=now,
        opener=fake_urlopen,
    )
    second = cache.get_or_mint(
        issuer="Iv1.client",
        private_key_pem=private_pem,
        installation_id=7,
        repositories=["repo"],
        now=now + timedelta(minutes=1),
        opener=fake_urlopen,
    )
    third = cache.get_or_mint(
        issuer="Iv1.client",
        private_key_pem=private_pem,
        installation_id=7,
        repositories=["repo"],
        now=now + timedelta(minutes=10),
        opener=fake_urlopen,
    )

    assert first.token == "ghs_1"
    assert second.token == "ghs_1"
    assert third.token == "ghs_2"
    assert len(calls) == 2


def test_installation_token_cache_separates_exact_permission_scopes() -> None:
    private_pem, _public_pem = _private_key_pair()
    now = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)
    requests: list[dict[str, Any]] = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse({
            "token": f"ghs_{len(requests)}",
            "expires_at": "2026-07-09T18:00:00Z",
        })

    cache = installation_tokens.InstallationTokenCache()
    common = {
        "issuer": "Iv1.client",
        "private_key_pem": private_pem,
        "installation_id": 7,
        "repository_ids": [1001],
        "now": now,
        "opener": fake_urlopen,
    }
    metadata = cache.get_or_mint(
        **common, permissions={"metadata": "read"},
    )
    issues = cache.get_or_mint(
        **common, permissions={"metadata": "read", "issues": "write"},
    )
    metadata_again = cache.get_or_mint(
        **common, permissions={"metadata": "read"},
    )

    assert metadata.token == metadata_again.token == "ghs_1"
    assert issues.token == "ghs_2"
    assert requests == [
        {
            "repository_ids": [1001],
            "permissions": {"metadata": "read"},
        },
        {
            "repository_ids": [1001],
            "permissions": {"metadata": "read", "issues": "write"},
        },
    ]


def test_installation_token_rejects_both_repository_restriction_shapes() -> None:
    private_pem, _public_pem = _private_key_pair()

    with pytest.raises(GitHubAppTokenError, match="repository ids or repository names"):
        installation_tokens.mint_installation_token(
            issuer="Iv1.client",
            private_key_pem=private_pem,
            installation_id=7,
            repository_ids=[1],
            repositories=["repo"],
            opener=lambda _request, _timeout: None,
        )
