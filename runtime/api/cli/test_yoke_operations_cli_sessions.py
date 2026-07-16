"""Focused CLI dispatch tests for session/orchestration wrappers."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_dispatch_ok,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                buf = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(err):
                    return cli_main(list(argv))


def test_sessions_touch_dispatches() -> None:
    assert _run("sessions", "touch", "--mode", "charge") == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.touch"
    assert req.target.kind == "global"
    assert req.payload == {"mode": "charge"}


def test_sessions_checkpoint_dispatches() -> None:
    assert _run(
        "sessions", "checkpoint",
        "--step", "2",
        "--action", "charge",
        "--chainable", "true",
        "--item-id", "42",
        "--task-num", "3",
        "--outcome", "completed",
        "--status", "implemented",
        "--required-path", "runtime/api/foo.py",
        "--pre-status", "implementing",
    ) == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.checkpoint"
    assert req.target.kind == "global"
    assert req.payload == {
        "step": 2,
        "action": "charge",
        "chainable": True,
        "outcome": "completed",
        "item_id": "42",
        "task_num": 3,
        "status": "implemented",
        "required_path": "runtime/api/foo.py",
        "pre_status": "implementing",
    }


def test_sessions_checkpoint_read_dispatches() -> None:
    assert _run("sessions", "checkpoint-read") == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.checkpoint_read"
    assert req.target.kind == "global"
    assert req.payload == {}


def test_sessions_offer_dispatches_with_explicit_session() -> None:
    assert _run(
        "sessions", "offer",
        "--executor", "codex",
        "--provider", "openai",
        "--workspace", "/tmp/workspace",
        "--lane", "primary",
        "--step", "2",
        "--supported-paths", "runtime/api/a.py,runtime/api/b.py",
        "--project", "yoke",
        "--session-id", "offer-session",
    ) == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.offer"
    assert req.actor.session_id == "offer-session"
    assert req.target.kind == "global"
    assert req.payload == {
        "executor": "codex",
        "provider": "openai",
        "workspace": "/tmp/workspace",
        "lane": "primary",
        "step": 2,
        "supported_paths": ["runtime/api/a.py", "runtime/api/b.py"],
        "project": "yoke",
    }


def test_sessions_ownership_guard_dispatches_item_ref() -> None:
    assert _run(
        "sessions", "ownership-guard",
        "--item", "42",
        "--project", "yoke",
    ) == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.ownership_guard"
    assert req.target.kind == "item"
    assert req.target.item_ref == "42"
    assert req.target.project_id == "yoke"
    assert req.payload == {}


def test_charge_schedule_dispatches() -> None:
    assert _run(
        "charge", "schedule",
        "--project", "yoke",
        "--wip-cap", "7",
    ) == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "charge.schedule"
    assert req.target.kind == "global"
    assert req.payload == {"project": "yoke", "wip_cap": 7}


def test_registry_maps_sessions_list_to_function_id() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("sessions", "list")][0] == "sessions.list"


def test_sessions_list_dispatches_filters_and_prints_pipe_rows() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "fields": ["session_id", "liveness", "mode", "claims"],
                "rows": [
                    {
                        "session_id": "s-1",
                        "liveness": "active",
                        "mode": "charge",
                        "claims": [
                            {"target_kind": "item", "target": "YOK-41"},
                            {"target_kind": "process", "target": "feed"},
                        ],
                    },
                ],
            },
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main([
                        "sessions", "list",
                        "--project", "yoke",
                        "--liveness", "active",
                        "--limit", "5",
                    ])

    assert rc == 0
    assert out.getvalue() == "s-1|active|charge|YOK-41,feed\n"
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "sessions.list"
    assert req.target.kind == "global"
    assert req.payload == {
        "project": "yoke",
        "liveness": "active",
        "limit": 5,
    }
