"""GitHub App JWT generation for installation-token exchanges."""

from __future__ import annotations

from datetime import datetime, timedelta

import jwt

from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    ensure_utc,
    require_nonempty_string,
    utc_now,
)

GITHUB_APP_JWT_IAT_BACKDATE_SECONDS = 60
GITHUB_APP_JWT_MAX_LIFETIME_SECONDS = 600


def generate_app_jwt(
    *,
    issuer: str | int,
    private_key_pem: str | bytes,
    now: datetime | None = None,
    lifetime_seconds: int = GITHUB_APP_JWT_MAX_LIFETIME_SECONDS,
) -> str:
    """Return an RS256 JWT accepted by GitHub App installation APIs."""

    selected_issuer = require_nonempty_string(issuer, "GitHub App JWT issuer")
    if _is_empty_key(private_key_pem):
        raise GitHubAppTokenError("GitHub App private key is required")
    if lifetime_seconds <= 0 or lifetime_seconds > GITHUB_APP_JWT_MAX_LIFETIME_SECONDS:
        raise GitHubAppTokenError(
            "GitHub App JWT lifetime must be between 1 and 600 seconds"
        )
    selected_now = ensure_utc(now or utc_now())
    payload = {
        "iat": int((
            selected_now - timedelta(seconds=GITHUB_APP_JWT_IAT_BACKDATE_SECONDS)
        ).timestamp()),
        "exp": int((selected_now + timedelta(seconds=lifetime_seconds)).timestamp()),
        "iss": selected_issuer,
    }
    encoded = jwt.encode(payload, private_key_pem, algorithm="RS256")
    return encoded.decode("utf-8") if isinstance(encoded, bytes) else str(encoded)


def _is_empty_key(private_key_pem: str | bytes) -> bool:
    if isinstance(private_key_pem, bytes):
        return not private_key_pem.strip()
    return not str(private_key_pem or "").strip()


__all__ = [
    "GITHUB_APP_JWT_IAT_BACKDATE_SECONDS",
    "GITHUB_APP_JWT_MAX_LIFETIME_SECONDS",
    "generate_app_jwt",
]
