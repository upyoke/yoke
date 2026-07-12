"""Cross-process serialization for machine GitHub App mutations and checks."""

from __future__ import annotations

from functools import wraps
from contextlib import contextmanager
from pathlib import Path
import threading

from yoke_cli.config import github_git_credential_document
from yoke_cli.config import github_git_credential_file


_LOCAL = threading.local()


class GitHubMachineOperationError(RuntimeError):
    """The canonical machine GitHub operation lock is unavailable."""


@contextmanager
def operation_lock(config_path: str | Path | None = None):
    """Serialize the complete machine-profile read/prove/refresh transaction."""

    depth = int(getattr(_LOCAL, "depth", 0))
    if depth:
        _LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
        return
    # Every supported --config path stores owned GitHub credentials in the same
    # machine secret root. Anchor the transaction lock there too, otherwise two
    # configs in different directories can rotate the same credential at once.
    lock_target = (
        github_git_credential_document.machine_secrets_dir()
        / ".github-machine-operation"
    )
    try:
        with github_git_credential_file.exclusive_lock(lock_target):
            _LOCAL.depth = 1
            try:
                yield
            finally:
                _LOCAL.depth = 0
    except github_git_credential_file.CredentialFileError as exc:
        raise GitHubMachineOperationError(
            "machine GitHub App operation lock is unavailable"
        ) from exc


def serialized_operation(error_type: type[Exception]):
    """Build a decorator that serializes machine-wide GitHub operations."""
    def decorate(operation):
        @wraps(operation)
        def wrapped(*args, **kwargs):
            try:
                selected_path = kwargs.get("config_path", kwargs.get("path"))
                with operation_lock(selected_path):
                    return operation(*args, **kwargs)
            except GitHubMachineOperationError as exc:
                raise error_type(
                    "machine GitHub App operation lock is unavailable"
                ) from exc

        return wrapped

    return decorate


__all__ = [
    "GitHubMachineOperationError",
    "operation_lock",
    "serialized_operation",
]
