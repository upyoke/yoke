"""Shared machine-config and credential fixtures for GitHub user-token tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from yoke_cli.config import github_git_credential_store as credential_store
from yoke_contracts.machine_config import schema as contract


class FakeResponse:
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


class RawResponse(FakeResponse):
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.url = "https://github.com/login/oauth/access_token"


NOW = datetime(2026, 7, 9, 17, 0, tzinfo=timezone.utc)


def configured_credential(
    tmp_path, *, expires_at: datetime, access_token: str | None = "stored-access",
) -> tuple[Any, Any]:
    credential_path = (
        tmp_path / "secrets" / f"github-app-user-{'a' * 32}.json"
    )
    document = {
        "schema_version": 2,
        "refresh_token": "old-refresh",
        "refresh_expires_at": (NOW + timedelta(days=30)).isoformat(),
    }
    if access_token is not None:
        document["cached_access"] = {
            "access_token": access_token,
            "expires_at": expires_at.isoformat(),
            "scope": "",
            "token_type": "bearer",
        }
    credential_store.write_credential_document(credential_path, document)
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


__all__ = ["NOW", "FakeResponse", "RawResponse", "configured_credential"]
