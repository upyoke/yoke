"""The stored access token a git command reuses instead of minting its own.

Refreshing a GitHub App user authorization rotates it, and the rotation revokes
the access token every other local process is already carrying. While the
credential document held only the refresh half, every read of it had to mint a
new token, so two concurrent pushes on one machine each revoked the other's
credential and git reported the rejection as a credential prompt — a push that
fails on a busy machine and succeeds on a quiet one.

Keeping the access token beside the refresh token that minted it turns the
common read into a lookup. The machine serves one token until it is genuinely
close to expiring, so the processes sharing it stop invalidating each other,
and the refresh exchange happens once per token lifetime rather than once per
network git command.

Storing it costs no reach: the document already holds the refresh token, which
mints access tokens for months, under the same owner-only permissions that an
access token expiring in hours now lives under.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

if __package__:
    from yoke_cli.config import github_git_credential_document as credential_document
    from yoke_contracts import github_app_tokens as token_contract
else:  # pragma: no cover - copied helper always uses its immutable siblings
    import _yoke_github_app_tokens as token_contract  # type: ignore
    import _yoke_github_git_credential_document as credential_document  # type: ignore


ACCESS_TOKEN_KEY = "access_token"
ACCESS_EXPIRES_AT_KEY = "expires_at"
REFRESH_MARGIN_SECONDS = (
    token_contract.GITHUB_APP_USER_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS
)


def access_state(
    payload: Mapping[str, Any], *, error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Return the access half of a credential document, empty when it has none.

    A document written before its first refresh carries no access token; that
    is the cache's cold state, not a fault. A document carrying an access token
    without a readable expiry is a fault, because nothing could decide when to
    stop serving it.
    """

    if payload.get(ACCESS_TOKEN_KEY) is None and (
        payload.get(ACCESS_EXPIRES_AT_KEY) is None
    ):
        return {}
    return {
        ACCESS_TOKEN_KEY: credential_document.required_string(
            payload.get(ACCESS_TOKEN_KEY), ACCESS_TOKEN_KEY, error_type,
        ),
        ACCESS_EXPIRES_AT_KEY: credential_document.parse_timestamp(
            payload.get(ACCESS_EXPIRES_AT_KEY), ACCESS_EXPIRES_AT_KEY, error_type,
        ).isoformat(),
        "scope": str(payload.get("scope") or ""),
        "token_type": str(payload.get("token_type") or "bearer"),
    }


def persisted_document(
    payload: Mapping[str, Any],
    *,
    schema_version: int,
    error_type: type[RuntimeError],
    ownership_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose one document holding both halves of the credential.

    Every writer goes through this, including the ownership mutations: a write
    that dropped the access half would silently evict the cache and send the
    next git command back to minting its own token.
    """

    return {
        **credential_document.persisted_document(
            payload,
            schema_version=schema_version,
            error_type=error_type,
            ownership_source=ownership_source,
        ),
        **access_state(payload, error_type=error_type),
    }


def usable_token_state(
    document: Mapping[str, Any],
    *,
    now: datetime,
    error_type: type[RuntimeError],
    margin_seconds: int = REFRESH_MARGIN_SECONDS,
) -> dict[str, Any] | None:
    """Return the token state still worth serving, or ``None`` to refresh.

    The margin is what keeps a command that starts just inside the window from
    finishing outside it: a token handed out with less life than the margin
    would be a race of a different shape.
    """

    state = access_state(document, error_type=error_type)
    if not state:
        return None
    expires_at = credential_document.parse_timestamp(
        state[ACCESS_EXPIRES_AT_KEY], ACCESS_EXPIRES_AT_KEY, error_type,
    )
    if expires_at - timedelta(seconds=margin_seconds) <= (
        credential_document.ensure_utc(now)
    ):
        return None
    return {
        **state,
        "refresh_token": credential_document.required_string(
            document.get("refresh_token"), "refresh_token", error_type,
        ),
        "refresh_expires_at": credential_document.parse_timestamp(
            document.get("refresh_expires_at"), "refresh_expires_at", error_type,
        ).isoformat(),
    }


def result(
    payload: Mapping[str, Any], *, path: Any, cached: bool, rotated: bool,
) -> dict[str, Any]:
    """Return one token payload naming where it came from."""

    return dict(
        payload,
        cached=cached,
        refresh_rotated=rotated,
        refresh_credential_ref=str(path),
    )


__all__ = [
    "ACCESS_EXPIRES_AT_KEY",
    "ACCESS_TOKEN_KEY",
    "REFRESH_MARGIN_SECONDS",
    "access_state",
    "persisted_document",
    "result",
    "usable_token_state",
]
