"""GitHub App identity model and issuer validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class GitHubAppIdentityVerificationError(RuntimeError):
    """The configured issuer does not identify the authenticated App."""


@dataclass(frozen=True)
class GitHubAppIdentity:
    app_id: int
    client_id: str
    slug: str


def validate_identity_payload(
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
    "validate_identity_payload",
]
