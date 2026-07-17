"""Helpers for composing public Yoke API and distribution URLs.

Hosted control APIs live behind the Platform tenant proxy. Package and
installer distribution remains on the dedicated ``api.*`` hosts. Keeping the
two authorities explicit prevents onboarding or machine-config generation from
mistaking the immutable package channel for a writable Yoke control plane.
"""

from __future__ import annotations

DISTRIBUTION_PROD_URL = "https://api.upyoke.com"
DISTRIBUTION_STAGE_URL = "https://api.stage.upyoke.com"
HOSTED_PROD_API_URL = "https://app.upyoke.com/api/orgs/upyoke"
HOSTED_STAGE_API_URL = "https://app.stage.upyoke.com/api/orgs/upyoke"
HOSTED_PLATFORM_URL = "https://app.upyoke.com"
HOSTED_STAGE_PLATFORM_URL = "https://app.stage.upyoke.com"

API_VERSION_PREFIX = "/v1"
AUTH_IDENTITY_PATH = f"{API_VERSION_PREFIX}/auth/identity"
FUNCTIONS_CALL_PATH = f"{API_VERSION_PREFIX}/functions/call"
FUNCTIONS_REGISTRY_PATH = f"{API_VERSION_PREFIX}/functions/registry"
HEALTH_PATH = f"{API_VERSION_PREFIX}/health"
UNIVERSE_EXPORT_PATH = f"{API_VERSION_PREFIX}/universe/export"


def join_api_url(api_url: str, path: str) -> str:
    """Join a service root or versioned base URL to a versioned API path."""
    base = str(api_url or "").rstrip("/")
    if path.startswith(f"{API_VERSION_PREFIX}/") and base.endswith(API_VERSION_PREFIX):
        base = base[: -len(API_VERSION_PREFIX)]
    return base + path


__all__ = [
    "API_VERSION_PREFIX",
    "AUTH_IDENTITY_PATH",
    "FUNCTIONS_CALL_PATH",
    "FUNCTIONS_REGISTRY_PATH",
    "HEALTH_PATH",
    "UNIVERSE_EXPORT_PATH",
    "DISTRIBUTION_PROD_URL",
    "DISTRIBUTION_STAGE_URL",
    "HOSTED_PROD_API_URL",
    "HOSTED_STAGE_API_URL",
    "HOSTED_PLATFORM_URL",
    "HOSTED_STAGE_PLATFORM_URL",
    "join_api_url",
]
