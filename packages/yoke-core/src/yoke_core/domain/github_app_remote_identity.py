"""Read-only GitHub App identity proof executed from a deploy origin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import shlex
from typing import Any

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    parse_json_object,
)


_REMOTE_APP_IDENTITY_PROGRAM = r"""
import json
import sys
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, url):
        return None

url = sys.argv[1]
token = sys.stdin.read().strip()
if not token:
    raise SystemExit(64)
request = urllib.request.Request(
    url,
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "yoke-github-app",
    },
    method="GET",
)
try:
    with urllib.request.build_opener(NoRedirect()).open(
        request, timeout=30,
    ) as response:
        if response.geturl() != url:
            raise ValueError("unexpected response origin")
        payload = json.load(response)
    selected = {key: payload.get(key) for key in ("id", "client_id", "slug")}
    sys.stdout.write(json.dumps(selected, separators=(",", ":")))
except Exception:
    sys.stderr.write("github_app_identity_request_failed\n")
    raise SystemExit(65)
""".strip()


class GitHubAppIdentityVerificationError(RuntimeError):
    """The configured issuer and private key do not identify one live App."""


@dataclass(frozen=True)
class GitHubAppIdentity:
    """Non-secret identity returned by GitHub's authenticated App endpoint."""

    app_id: int
    client_id: str
    slug: str


def verify_github_app_identity(
    *,
    runner: Any,
    env: Any,
    issuer: str,
    private_key_pem: str,
    api_url: str,
    now: datetime | None = None,
) -> GitHubAppIdentity:
    """Sign locally, then prove App identity from the target network."""
    try:
        endpoint = validate_github_api_endpoint(api_url)
        app_jwt = generate_app_jwt(
            issuer=issuer,
            private_key_pem=private_key_pem,
            now=now,
        )
    except (GitHubApiOriginError, GitHubAppTokenError) as exc:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity verification could not sign a valid JWT"
        ) from exc

    from yoke_core.domain.deploy_remote import run_remote

    app_url = endpoint.url("/app")
    remote_command = " ".join(
        (
            "python3",
            "-c",
            shlex.quote(_REMOTE_APP_IDENTITY_PROGRAM),
            shlex.quote(app_url),
        )
    )
    result = run_remote(
        runner,
        env,
        remote_command,
        input_text=app_jwt,
        timeout=45,
    )
    if not result.ok:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity verification request failed from the deployment origin"
        )
    try:
        payload = parse_json_object(
            result.stdout.encode("utf-8"),
            "GitHub App identity",
        )
    except GitHubAppTokenError as exc:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity verification returned an invalid response"
        ) from exc
    return _validate_identity_payload(issuer, payload)


def _validate_identity_payload(
    issuer: str,
    payload: dict[str, Any],
) -> GitHubAppIdentity:
    raw_app_id = payload.get("id")
    if isinstance(raw_app_id, bool) or not isinstance(raw_app_id, (int, str)):
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response omitted a valid App id"
        )
    app_id_text = str(raw_app_id).strip()
    if not app_id_text.isdigit() or int(app_id_text) <= 0:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response omitted a valid App id"
        )
    app_id = int(app_id_text)
    client_id = str(payload.get("client_id") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    if not client_id:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response omitted its client id"
        )
    if str(issuer).strip() not in {str(app_id), client_id}:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response does not match the configured issuer"
        )
    if not slug:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response omitted its slug"
        )
    return GitHubAppIdentity(app_id=app_id, client_id=client_id, slug=slug)


__all__ = [
    "GitHubAppIdentity",
    "GitHubAppIdentityVerificationError",
    "verify_github_app_identity",
]
