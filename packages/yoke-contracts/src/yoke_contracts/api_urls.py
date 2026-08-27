"""Helpers for composing public Yoke API and distribution URLs.

Hosted control APIs live behind the Platform tenant proxy. Package and
installer distribution remains on the dedicated ``api.*`` hosts. The AWS
bootstrap template rides the same release tree but CloudFormation fetches it
from the distribution bucket's regional S3 origin. Keeping these authorities
explicit prevents onboarding or machine-config generation from mistaking an
immutable artifact channel for a writable Yoke control plane.
"""

from __future__ import annotations

DISTRIBUTION_PROD_URL = "https://api.upyoke.com"
DISTRIBUTION_STAGE_URL = "https://api.stage.upyoke.com"
AWS_BOOTSTRAP_TEMPLATE_PROD_URL = (
    "https://upyoke-distribution-prod.s3.us-east-1.amazonaws.com"
)
AWS_BOOTSTRAP_TEMPLATE_STAGE_URL = (
    "https://upyoke-distribution-stage.s3.us-east-1.amazonaws.com"
)
# Environment override for the distribution host, read by the public installer.
# Hosted-channel-aware surfaces also use it to select their matching artifact
# authority; the CloudFormation bootstrap link maps it to a regional S3 origin.
DISTRIBUTION_BASE_URL_ENV = "YOKE_INSTALL_BASE_URL"
HOSTED_PROD_API_URL = "https://app.upyoke.com/api/orgs/upyoke"
HOSTED_STAGE_API_URL = "https://app.stage.upyoke.com/api/orgs/upyoke-stage-1"
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
    "AWS_BOOTSTRAP_TEMPLATE_PROD_URL",
    "AWS_BOOTSTRAP_TEMPLATE_STAGE_URL",
    "AUTH_IDENTITY_PATH",
    "FUNCTIONS_CALL_PATH",
    "FUNCTIONS_REGISTRY_PATH",
    "HEALTH_PATH",
    "UNIVERSE_EXPORT_PATH",
    "DISTRIBUTION_BASE_URL_ENV",
    "DISTRIBUTION_PROD_URL",
    "DISTRIBUTION_STAGE_URL",
    "HOSTED_PROD_API_URL",
    "HOSTED_STAGE_API_URL",
    "HOSTED_PLATFORM_URL",
    "HOSTED_STAGE_PLATFORM_URL",
    "join_api_url",
]
