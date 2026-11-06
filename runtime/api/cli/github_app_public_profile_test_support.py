# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
        **{key: value for key, value in values.items() if key != "available"}
    )
