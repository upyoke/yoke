"""Compatibility import for public Yoke API URL helpers."""

from __future__ import annotations

from yoke_contracts.api_urls import (
    API_VERSION_PREFIX,
    AUTH_IDENTITY_PATH,
    FUNCTIONS_CALL_PATH,
    FUNCTIONS_REGISTRY_PATH,
    HEALTH_PATH,
    join_api_url,
)


__all__ = [
    "API_VERSION_PREFIX",
    "AUTH_IDENTITY_PATH",
    "FUNCTIONS_CALL_PATH",
    "FUNCTIONS_REGISTRY_PATH",
    "HEALTH_PATH",
    "join_api_url",
]
