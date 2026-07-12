"""Helpers for composing public Yoke API URLs.

Hosted-platform endpoints: upyoke.com is the operator-hosted platform and the
official package distribution channel. The same hosts serve the platform API
and the distribution channel (``/install``, ``/dist/*``, ``/simple/``). API
connectivity is mode-aware — the machine-config connection entry is the
authority in every deployment mode, and only the hosted sign-in flow defaults
to these endpoints. Package distribution defaults to the hosted channel in
every mode, always with an override path (installer ``--base-url`` /
``YOKE_INSTALL_BASE_URL``, release tooling ``--base-url``).
"""

from __future__ import annotations

HOSTED_PROD_URL = "https://api.upyoke.com"
HOSTED_STAGE_URL = "https://api.stage.upyoke.com"
HOSTED_PLATFORM_URL = "https://app.upyoke.com"

API_VERSION_PREFIX = "/v1"
AUTH_IDENTITY_PATH = f"{API_VERSION_PREFIX}/auth/identity"
FUNCTIONS_CALL_PATH = f"{API_VERSION_PREFIX}/functions/call"
FUNCTIONS_REGISTRY_PATH = f"{API_VERSION_PREFIX}/functions/registry"
HEALTH_PATH = f"{API_VERSION_PREFIX}/health"


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
    "HOSTED_PROD_URL",
    "HOSTED_STAGE_URL",
    "HOSTED_PLATFORM_URL",
    "join_api_url",
]
