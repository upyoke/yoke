"""Verify the core container's mounted GitHub App key without exposing it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.request

from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
)
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_identity import validate_identity_payload
from yoke_contracts.github_origin import validate_github_api_endpoint


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, url):
        del request, file_pointer, code, message, headers, url
        return None


def verify_mounted_identity() -> None:
    """Sign and call ``GET /app`` using only container-mounted authority."""
    issuer = os.environ[GITHUB_APP_ISSUER_ENV].strip()
    api_url = os.environ[GITHUB_APP_API_URL_ENV].strip()
    key_path = Path(os.environ[GITHUB_APP_PRIVATE_KEY_FILE_ENV])
    private_key = key_path.read_text(encoding="utf-8")
    token = generate_app_jwt(issuer=issuer, private_key_pem=private_key)
    endpoint = validate_github_api_endpoint(api_url)
    url = endpoint.url("/app")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "yoke-github-app",
        },
    )
    with urllib.request.build_opener(_NoRedirect()).open(
        request, timeout=30,
    ) as response:
        if response.geturl() != url:
            raise ValueError("unexpected response origin")
        payload = json.load(response)
    validate_identity_payload(issuer, payload)


def main() -> int:
    try:
        verify_mounted_identity()
    except Exception:
        print("GitHub App identity verification failed", file=sys.stderr)
        return 1
    print("GitHub App identity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "verify_mounted_identity"]
