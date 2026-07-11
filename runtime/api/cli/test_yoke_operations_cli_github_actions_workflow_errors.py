"""Error-boundary coverage for concise GitHub Actions CLI adapters."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import github_actions_workflow as workflow_mod
from runtime.api.cli.test_yoke_operations_cli_github_actions_workflow import (
    _CAPTURED_REQUESTS,
    _run,
)


_VALID_COMMANDS = [
    (
        "github-actions", "trigger", "o/r", "ci.yml",
        "--request-id", "r", "--correlation-input", "yoke_dispatch_id",
        "--project", "p",
    ),
    ("github-actions", "find-run", "o/r", "ci.yml", "abc", "--project", "p"),
    ("github-actions", "poll", "o/r", "7", "--project", "p"),
    ("github-actions", "jobs-count", "o/r", "7", "--project", "p"),
]


@pytest.fixture(autouse=True)
def _reset_captured_requests() -> None:
    _CAPTURED_REQUESTS.clear()


@pytest.mark.parametrize("argv", _VALID_COMMANDS)
def test_hosted_errors_use_transport_exit_code(argv: tuple[str, ...]) -> None:
    rc, out, err = _run(
        *argv,
        error={"code": "permission_denied", "message": "project grant required"},
    )
    assert rc == workflow_mod.GITHUB_ACTIONS_OPERATION_ERROR_EXIT
    assert out == ""
    assert "permission_denied" in err
    assert "project grant required" in err
    assert len(_CAPTURED_REQUESTS) == 1


@pytest.mark.parametrize(
    "argv",
    [
        tuple("invalid" if token == "o/r" else token for token in command)
        for command in _VALID_COMMANDS
    ],
)
def test_repo_slug_is_validated_before_relay(argv: tuple[str, ...]) -> None:
    rc, _out, err = _run(*argv)
    assert rc == 2
    assert "repo must be owner/name" in err
    assert _CAPTURED_REQUESTS == []
