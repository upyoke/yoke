"""Dispatch-path tests for ``yoke github pr create``.

Mirrors the stub-dispatch harness in
test_yoke_operations_cli_github_actions: the dispatcher seam is
patched so no handler, DB, or network is touched — the assertions cover
flag -> payload mapping into the ``github.pr.create`` function call.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List, Optional
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    stdin_text: Optional[str] = None,
    session_id: str = "test-session",
) -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with patch("sys.stdin", io.StringIO(stdin_text or "")):
                    with redirect_stdout(io.StringIO()), \
                            redirect_stderr(io.StringIO()):
                        return cli_main(list(argv))


class TestRegistry:
    def test_tokens_resolve_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[("github", "pr", "create")][0] == (
            "github.pr.create"
        )


class TestPrCreate:
    def test_dispatches_with_required_flags(self) -> None:
        rc = _run(
            "github", "pr", "create",
            "--title", "cli sweep: function-call fixes", "--head", "cli-sweep-fixes",
            "--project", "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "github.pr.create"
        assert req.target.kind == "global"
        # body key omitted when no description flag given.
        assert req.payload == {
            "title": "cli sweep: function-call fixes",
            "head": "cli-sweep-fixes",
            "base": "main",
            "draft": False,
            "project": "yoke",
        }

    def test_optional_flags_pass_through(self) -> None:
        rc = _run(
            "github", "pr", "create",
            "--title", "T", "--head", "h",
            "--base", "stage", "--body", "One-liner.",
            "--draft", "--project", "externalwebapp",
        )
        assert rc == 0
        payload = _CAPTURED_REQUESTS[-1].payload
        assert payload["base"] == "stage"
        assert payload["body"] == "One-liner."
        assert payload["draft"] is True
        assert payload["project"] == "externalwebapp"

    def test_body_stdin_reads_multiline_body(self) -> None:
        rc = _run(
            "github", "pr", "create",
            "--title", "T", "--head", "h", "--body-stdin",
            "--project", "yoke",
            stdin_text="## Summary\n\nDetails.\n",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["body"] == "## Summary\n\nDetails.\n"

    def test_body_and_body_stdin_are_mutually_exclusive(self) -> None:
        rc = _run(
            "github", "pr", "create",
            "--title", "T", "--head", "h",
            "--body", "x", "--body-stdin", "--project", "yoke",
            stdin_text="y",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_empty_stdin_body_returns_two(self) -> None:
        rc = _run(
            "github", "pr", "create",
            "--title", "T", "--head", "h", "--body-stdin",
            "--project", "yoke",
            stdin_text="  \n",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_title_returns_two(self) -> None:
        rc = _run(
            "github", "pr", "create", "--head", "h",
            "--project", "yoke",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_head_returns_two(self) -> None:
        rc = _run(
            "github", "pr", "create", "--title", "T",
            "--project", "yoke",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_project_returns_two(self) -> None:
        rc = _run(
            "github", "pr", "create", "--title", "T", "--head", "h",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
