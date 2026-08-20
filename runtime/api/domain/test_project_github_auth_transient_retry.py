"""A machine authorization read that fails does not end the work.

The local user-token provider can fail because the stored authorization is
gone, or because the read collided with a sibling process or a slow GitHub.
The second is retried and, if it never clears, reported as retryable. Neither
one ends an operation the project's installation is itself authorized to
perform, which is what an operation gets by naming no authority at all.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_READ_ATTEMPTS,
    TransientGitHubAuthError,
    is_transient_auth_failure,
)
from yoke_core.domain import project_github_auth as pga
from yoke_core.domain import project_github_auth_tokens
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_INSTALLATION,
    GITHUB_AUTHORITY_USER,
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
    message = str(raised.value)
    assert "did not land" in message
    assert "yoke github status" in message
    assert "reconnect" in message.lower()
    assert "reconnect" in pga.repair_command_hint(raised.value, "yoke").lower()
    # The provider's own text can carry a credential path, so it rides on the
    # cause rather than in anything the operator is shown.
    assert "machine GitHub App authorization is not configured" not in message
    assert "machine GitHub App authorization is not configured" in str(
        raised.value.__cause__
    )


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


def _bound_state() -> ProjectGithubState:
    return ProjectGithubState(
        project_slug="yoke",
        project_id=1,
        has_capability=True,
        binding={
            "status": "active",
            "github_repo": "upyoke/yoke",
            "installation_id": "12345",
            "repository_id": "4567",
            "api_url": API_URL,
        },
        installation={
            "status": "active",
            "permissions": json.dumps(
                dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
            ),
            "api_url": API_URL,
        },
    )


class TestAFailedReadDoesNotEndInstallationCapableWork:
    """The closeouts and merges that hit this every day never needed a person.

    Every one of them named no authority, inherited the strongest possible
    requirement, and died on a machine token the operation had no use for.
    """

    @pytest.fixture(autouse=True)
    def _bound_project(self, monkeypatch):
        monkeypatch.setattr(
            pga, "read_github_state", lambda *_a, **_k: _bound_state(),
        )
        monkeypatch.setattr(
            pga, "register_installation_token", lambda *_a, **_k: None,
        )
        monkeypatch.setattr(
            pga,
            "read_app_credentials",
            lambda *_a, **_k: SimpleNamespace(
                issuer="1", private_key_pem="k", api_url=API_URL,
                private_key_file="/k.pem",
            ),
        )
        monkeypatch.setattr(
            pga,
            "mint_bound_installation_token",
            lambda *_a, **_k: SimpleNamespace(
                token="ghs_installation",
                expires_at=SimpleNamespace(isoformat=lambda: "later"),
            ),
        )

    def _read_fails_with(self, monkeypatch, error) -> None:
        def _refuse(state, **_kwargs):
            raise error(state.project_slug, "the read did not land")

        monkeypatch.setattr(pga, "resolve_local_user_token", _refuse)

    def test_the_inherited_authority_is_the_weakest_sufficient_one(self) -> None:
        import inspect

        signature = inspect.signature(pga.resolve_project_github_auth)
        assert (
            signature.parameters["required_authority"].default
            == GITHUB_AUTHORITY_INSTALLATION
        )

    @pytest.mark.parametrize(
        "error", [UserAuthorizationTransient, UserAuthorizationUnavailable],
    )
    def test_a_failed_read_falls_through_to_the_installation(
        self, monkeypatch, error,
    ) -> None:
        self._read_fails_with(monkeypatch, error)

        resolved = pga.resolve_project_github_auth("yoke")

        assert resolved.token == "ghs_installation"
        assert resolved.token_source == GITHUB_AUTHORITY_INSTALLATION

    @pytest.mark.parametrize(
        "error", [UserAuthorizationTransient, UserAuthorizationUnavailable],
    )
    def test_work_attributed_to_a_person_still_refuses(
        self, monkeypatch, error,
    ) -> None:
        self._read_fails_with(monkeypatch, error)

        with pytest.raises(error):
            pga.resolve_project_github_auth(
                "yoke", required_authority=GITHUB_AUTHORITY_USER,
            )
