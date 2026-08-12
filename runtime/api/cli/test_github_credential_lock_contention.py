"""Contended machine GitHub reads stay bounded and stay retryable.

The machine credential lock is shared by every local GitHub operation, so a
busy machine used to look exactly like a missing authorization: an unbounded
wait, then a verdict prescribing a sign-in. Waiting is bounded now, and every
layer above reports contention as retryable instead.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import urllib.error

import pytest

from yoke_cli.commands import merge_item_local_runtime
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_machine_operation
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_cli.config import github_user_tokens
from yoke_contracts.github_auth_transience import is_transient_auth_failure


def _held_lock(target: Path) -> int:
    """Hold the lock the way another local process would."""

    lock_path = target.with_name(target.name + ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def test_contended_lock_gives_up_its_turn_instead_of_blocking(
    tmp_path: Path,
) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    target = secrets / "github-app-user.json"
    descriptor = _held_lock(target)
    slept: list[float] = []
    clock = iter([0.0, 0.0, 0.4, 0.9, 1.2])

    try:
        with pytest.raises(credential_file.CredentialFileBusy) as raised:
            with credential_file.exclusive_lock(
                target,
                wait_seconds=1.0,
                sleep=slept.append,
                monotonic=lambda: next(clock),
            ):
                pass
    finally:
        os.close(descriptor)

    assert slept, "a waiter queues politely before reporting contention"
    assert "another local Yoke operation" in str(raised.value)


def test_uncontended_lock_is_taken_immediately(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    target = secrets / "github-app-user.json"
    slept: list[float] = []

    with credential_file.exclusive_lock(target, sleep=slept.append):
        held = True

    assert held is True
    assert slept == []


def test_machine_operation_lock_reports_contention_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def busy(*args, **kwargs):
        raise credential_file.CredentialFileBusy("held by another operation")

    monkeypatch.setattr(credential_file, "exclusive_lock", busy)

    with pytest.raises(github_machine_operation.GitHubMachineOperationBusy) as raised:
        with github_machine_operation.operation_lock():
            pass

    assert is_transient_auth_failure(raised.value) is True
    assert "reconnect" not in str(raised.value).lower()


def test_serialized_operations_report_the_contention_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OperationError(RuntimeError):
        pass

    def busy(*args, **kwargs):
        raise credential_file.CredentialFileBusy("held by another operation")

    monkeypatch.setattr(credential_file, "exclusive_lock", busy)

    @github_machine_operation.serialized_operation(OperationError)
    def operation() -> None:  # pragma: no cover - lock refuses before the body
        raise AssertionError("the operation body must not run")

    with pytest.raises(OperationError) as raised:
        operation()

    assert "holding the machine operation lock" in str(raised.value)


@pytest.mark.parametrize("failure,transient", [
    (github_machine_operation.GitHubMachineOperationBusy("busy"), True),
    (
        github_user_tokens.GitHubUserTokenError("refresh failed"),
        False,
    ),
])
def test_local_access_classifies_its_own_failures(
    failure: Exception, transient: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_failure(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        github_local_user_access.github_machine_operation,
        "operation_lock",
        raise_failure,
    )

    with pytest.raises(github_local_user_access.GitHubLocalUserAccessError) as raised:
        github_local_user_access.access_token()

    assert isinstance(
        raised.value,
        github_local_user_access.TransientGitHubLocalUserAccessError,
    ) is transient


@pytest.mark.parametrize("status,transient", [
    (401, True), (429, True), (503, True), (404, False), (400, False),
])
def test_refresh_response_status_decides_retryability(
    status: int, transient: bool,
) -> None:
    http_error = urllib.error.HTTPError(
        "https://github.com/login/oauth/access_token",
        status,
        "refused",
        hdrs=None,
        fp=None,
    )
    try:
        try:
            raise http_error
        except urllib.error.HTTPError as exc:
            raise github_user_tokens.GitHubUserTokenError("refresh failed") from exc
    except github_user_tokens.GitHubUserTokenError as wrapped:
        assert (
            github_local_user_access.is_transient_access_failure(wrapped) is transient
        )


def test_merge_child_separates_retry_guidance_from_reconnect_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        merge_path_binding.machine_config,
        "github_config",
        lambda *args, **kwargs: {"api_url": "https://api.github.com"},
    )
    monkeypatch.setattr(
        merge_path_binding.github_app_public_profile,
        "selected_https_service_api_url",
        lambda *args, **kwargs: None,
    )

    def raise_transient(*args, **kwargs):
        raise github_local_user_access.TransientGitHubLocalUserAccessError("busy")

    monkeypatch.setattr(
        merge_item_local_runtime.github_local_user_access,
        "access_token",
        raise_transient,
    )
    _endpoint, provider = merge_item_local_runtime._machine_authority()

    with pytest.raises(
        merge_item_local_runtime.TransientLocalMergeGithubAuthorityError
    ) as retryable:
        provider()

    assert is_transient_auth_failure(retryable.value) is True
    assert "yoke github connect" not in str(retryable.value)

    def raise_permanent(*args, **kwargs):
        raise github_local_user_access.GitHubLocalUserAccessError("not configured")

    monkeypatch.setattr(
        merge_item_local_runtime.github_local_user_access,
        "access_token",
        raise_permanent,
    )
    _endpoint, provider = merge_item_local_runtime._machine_authority()

    with pytest.raises(
        merge_item_local_runtime.LocalMergeGithubAuthorityError
    ) as permanent:
        provider()

    assert is_transient_auth_failure(permanent.value) is False
    assert "yoke github connect" in str(permanent.value)
