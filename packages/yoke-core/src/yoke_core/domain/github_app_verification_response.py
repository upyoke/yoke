"""Bounded response reads for GitHub App trust-verification calls."""

from __future__ import annotations

from yoke_core.domain.github_response_safety import (
    GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES as GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES,
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES as GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES,
    GitHubResponseTooLargeError,
    read_bounded_response,
)


class GitHubAppVerificationResponseError(ValueError):
    """A verification response exceeded its safe parsing envelope."""


def require_unredirected_verification_response(
    response,
    *,
    expected_url: str,
) -> None:
    """Reject even same-origin redirects on identity and binding proofs."""
    final_url = str(getattr(response, "geturl", lambda: expected_url)())
    if final_url != expected_url:
        raise GitHubAppVerificationResponseError(
            "GitHub App verification requests must not redirect"
        )


def read_bounded_verification_response(
    response,
    *,
    limit_bytes: int = GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES,
) -> bytes:
    """Read one response with a one-byte overflow sentinel."""
    try:
        return read_bounded_response(
            response,
            limit_bytes=limit_bytes,
            label="GitHub App verification response",
        )
    except GitHubResponseTooLargeError:
        raise GitHubAppVerificationResponseError(
            "GitHub App verification response exceeded the size limit"
        ) from None
    except Exception:
        raise GitHubAppVerificationResponseError(
            "GitHub App verification response could not be read"
        ) from None


__all__ = [
    "GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES",
    "GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES",
    "GitHubAppVerificationResponseError",
    "read_bounded_verification_response",
    "require_unredirected_verification_response",
]
