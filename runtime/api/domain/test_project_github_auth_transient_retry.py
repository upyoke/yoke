"""Retry-shaped machine authorization reads never prescribe a reconnect.

The local user-token provider can fail because the stored authorization is
gone, or because the read collided with a sibling process or a slow GitHub.
Only the first earns the sign-in prescription; the second is retried and, if
it never clears, reported as retryable.
"""

from __future__ import annotations

import pytest

from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_READ_ATTEMPTS,
    TransientGitHubAuthError,
    is_transient_auth_failure,
)
from yoke_core.domain import project_github_auth as pga
from yoke_core.domain import project_github_auth_tokens
from yoke_core.domain.project_github_auth_models import (
    ProjectGithubState,
    UserAuthorizationTransient,
    UserAuthorizationUnavailable,
)


API_URL = "https://api.github.com"


class _BusyRead(TransientGitHubAuthError):
    """Stand-in for a client-side read that collided with another holder."""


def _state() -> ProjectGithubState:
    return ProjectGithubState(
        project_slug="yoke",
        project_id=1,
        has_capability=True,
        binding={"api_url": API_URL, "installation_id": "12345"},
        installation={"api_url": API_URL},
    )


def _resolve(provider, waits: list[float]) -> str | None:
    with pga.bind_local_github_user_token_provider(provider, api_url=API_URL):
        return project_github_auth_tokens.resolve_local_user_token(
            _state(), sleep=waits.append,
        )


def test_transient_read_resolves_on_retry_without_reconnect_advice() -> None:
    attempts: list[int] = []
    waits: list[float] = []

    def provider() -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise _BusyRead("another local operation holds the machine lock")
        return "gho_user"

    assert _resolve(provider, waits) == "gho_user"
    assert len(attempts) == 2
    assert waits and waits[0] > 0


def test_exhausted_transient_reads_stay_retryable() -> None:
    attempts: list[int] = []
    waits: list[float] = []

    def provider() -> str:
        attempts.append(1)
        raise _BusyRead("another local operation holds the machine lock")

    with pytest.raises(UserAuthorizationTransient) as raised:
        _resolve(provider, waits)

    assert len(attempts) == GITHUB_AUTH_READ_ATTEMPTS
    assert len(waits) == GITHUB_AUTH_READ_ATTEMPTS - 1
    assert raised.value.code == "user_authorization_transient"
    message = str(raised.value)
    assert "reconnect" not in message.lower()
    assert "retry" in message.lower()
    hint = pga.repair_command_hint(raised.value, "yoke")
    assert "reconnect" not in hint.lower()
    assert "retry" in hint.lower()


def test_absent_authorization_still_prescribes_a_reconnect() -> None:
    attempts: list[int] = []
    waits: list[float] = []

    def provider() -> str:
        attempts.append(1)
        raise RuntimeError("machine GitHub App authorization is not configured")

    with pytest.raises(UserAuthorizationUnavailable) as raised:
        _resolve(provider, waits)

    assert attempts == [1]
    assert waits == []
    assert raised.value.code == "user_authorization_unavailable"
    assert "reconnect" in str(raised.value).lower()
    assert "reconnect" in pga.repair_command_hint(raised.value, "yoke").lower()


def test_empty_token_is_an_invalid_authorization_not_a_retry() -> None:
    waits: list[float] = []

    with pytest.raises(UserAuthorizationUnavailable):
        _resolve(lambda: "   ", waits)

    assert waits == []


def test_transience_is_read_through_the_raised_from_chain() -> None:
    try:
        try:
            raise _BusyRead("lock held")
        except _BusyRead as busy:
            raise RuntimeError("machine authority unavailable") from busy
    except RuntimeError as wrapped:
        assert is_transient_auth_failure(wrapped) is True

    try:
        try:
            raise _BusyRead("lock held")
        except _BusyRead:
            raise RuntimeError("machine authority unavailable")
    except RuntimeError as unlinked:
        assert is_transient_auth_failure(unlinked) is False
