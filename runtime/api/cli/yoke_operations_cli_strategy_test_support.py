# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

from contextlib import redirect_stderr, redirect_stdout

from pathlib import Path

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
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


def _stub_call_dispatcher(**kwargs) -> FunctionCallResponse:
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs["actor"],
        target=kwargs["target"],
        payload=kwargs.get("payload") or {},
    )
    return _stub_ok(request)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    stdin_text: Optional[str] = None,
    session_id: Optional[str] = "test-session",
    extra_env: Optional[dict] = None,
) -> int:
    # Transport isolation (real machine config vs in-process dispatch
    # stub) is owned by the autouse ``_isolate_machine_config`` fixture
    # in this directory's conftest.
    env = {}
    if session_id is not None:
        env["YOKE_SESSION_ID"] = session_id
    if extra_env:
        env.update(extra_env)
    with patch.dict("os.environ", env, clear=session_id is None):
        with patch(
            "yoke_cli.transport.dispatcher._resolve_session_id",
            return_value=session_id,
        ):
            with patch(
                "yoke_cli.commands._helpers.call_dispatcher",
                side_effect=_stub_call_dispatcher,
            ):
                with patch(
                    "yoke_cli.commands.adapters.strategy_render.call_dispatcher",
                    side_effect=_stub_call_dispatcher,
                ):
                    with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                        with patch("sys.stdin", io.StringIO(stdin_text or "")):
                            with (
                                redirect_stdout(io.StringIO()),
                                redirect_stderr(io.StringIO()),
                            ):
                                return cli_main(list(argv))


def _seed_view(root: Path, slug: str, text: str = "") -> str:
    """Drop a rendered-looking file under root/.yoke/strategy/."""
    docs_dir = root / ".yoke" / "strategy"
    docs_dir.mkdir(parents=True, exist_ok=True)
    body = text or f"<!-- header {slug} -->\n# {slug}\n"
    (docs_dir / f"{slug}.md").write_text(body, encoding="utf-8")
    return body
