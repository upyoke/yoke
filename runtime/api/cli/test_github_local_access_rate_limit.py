"""Rate-limit 403s on local GitHub access are transient, not reconnect."""

from __future__ import annotations

import io
import urllib.error

from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_user_tokens


def _http_error(status: int, body: bytes, headers: dict[str, str] | None = None):
    return urllib.error.HTTPError(
        "https://api.github.com/user",
        status,
        "Forbidden",
        hdrs=headers or {},  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


def _wrapped(http_error: urllib.error.HTTPError) -> Exception:
    try:
        try:
            raise http_error
        except urllib.error.HTTPError as exc:
            raise github_user_tokens.GitHubUserTokenError(
                "refresh failed; reconnect GitHub"
            ) from exc
    except github_user_tokens.GitHubUserTokenError as wrapped:
        return wrapped


def test_rate_limit_403_is_transient_and_names_reset():
    wrapped = _wrapped(_http_error(
        403,
        b'{"message":"API rate limit exceeded for user ID 1"}',
        {"X-RateLimit-Reset": "1736899200", "X-RateLimit-Remaining": "0"},
    ))
    assert github_local_user_access.is_transient_access_failure(wrapped) is True

    message = github_local_user_access._transient_access_message(wrapped)
    assert "rate-limited" in message.lower()
    assert "1736899200" in message
    assert "reconnect" not in message.lower()


def test_secondary_rate_limit_403_is_transient_without_reconnect():
    wrapped = _wrapped(_http_error(
        403,
        b'{"message":"You have exceeded a secondary rate limit"}',
    ))
    assert github_local_user_access.is_transient_access_failure(wrapped) is True
    message = github_local_user_access._transient_access_message(wrapped)
    assert "reconnect" not in message.lower()


def test_permission_403_stays_permanent():
    wrapped = _wrapped(_http_error(
        403,
        b'{"message":"Resource not accessible by integration"}',
        {"X-RateLimit-Remaining": "4999"},
    ))
    assert github_local_user_access.is_transient_access_failure(wrapped) is False
