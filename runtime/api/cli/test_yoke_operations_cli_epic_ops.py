"""CLI parser coverage for epic ops and conduct pipeline wrappers."""

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


_CAPTURED: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"body": "row", "message": "ok", "stdout": "pipeline\n"},
    )


@pytest.fixture(autouse=True)
def _reset() -> None:
    _CAPTURED.clear()


def _run(*argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    return cli_main(list(argv))


@pytest.mark.parametrize(
    ("argv", "function", "payload"),
    [
        (
            ("workflow-item", "epic-task", "get",
             "--epic", "501", "--task-num", "3"),
            "workflow_item.epic_task.get",
            {},
        ),
        (
            ("workflow-item", "epic-task", "simulation-get",
             "--epic", "501", "--phase", "integration"),
            "workflow_item.epic_task.simulation_get",
            {"phase": "integration"},
        ),
        (
            ("workflow-item", "epic-task", "file-add",
             "--epic", "501", "--task-num", "3",
             "--file-path", "runtime/api/foo.py", "--action", "modify"),
            "workflow_item.epic_task.file_add",
            {"file_path": "runtime/api/foo.py", "action": "modify"},
        ),
        (
            ("workflow-item", "epic-task", "history-insert",
             "--epic", "501", "--task-num", "3",
             "--from-status", "none", "--to-status", "planned",
             "--note", "created"),
            "workflow_item.epic_task.history_insert",
            {"from_status": "none", "to_status": "planned", "note": "created"},
        ),
    ],
)
def test_epic_task_ops_dispatch(argv, function: str, payload: dict) -> None:
    assert _run(*argv) == 0
    req = _CAPTURED[-1]
    assert req.function == function
    assert req.target.kind == "epic_task"
    assert req.target.epic_id == 501
    assert req.payload == payload


@pytest.mark.parametrize(
    ("argv", "function", "payload"),
    [
        (
            ("workflow-item", "epic-dispatch-chain", "get",
             "--epic", "501", "--worktree", "lane-a"),
            "workflow_item.epic_dispatch_chain.get",
            {"worktree": "lane-a"},
        ),
        (
            ("workflow-item", "epic-dispatch-chain", "list",
             "--epic", "501"),
            "workflow_item.epic_dispatch_chain.list",
            {},
        ),
        (
            ("workflow-item", "epic-dispatch-chain", "update",
             "--epic", "501", "--worktree", "lane-a",
             "--field", "queue", "--value", "[1,2]"),
            "workflow_item.epic_dispatch_chain.update",
            {"worktree": "lane-a", "field": "queue", "value": "[1,2]"},
        ),
        (
            ("workflow-item", "epic-dispatch-chain", "refresh-activation",
             "--epic", "501", "--worktree", "lane-a", "--task-num", "3"),
            "workflow_item.epic_dispatch_chain.refresh_activation",
            {"worktree": "lane-a", "task_num": 3},
        ),
    ],
)
def test_dispatch_chain_ops_dispatch(argv, function: str, payload: dict) -> None:
    assert _run(*argv) == 0
    req = _CAPTURED[-1]
    assert req.function == function
    assert req.target.epic_id == 501
    assert req.target.task_num is None
    assert req.payload == payload


def test_conduct_status_pipeline_dispatches_claim_bypass() -> None:
    assert _run(
        "conduct", "epic-task", "update-status",
        "--epic", "501", "--task-num", "3",
        "--status", "implementing", "--note", "retry",
        "--no-rebuild", "--claim-bypass", "simulation-autofix:epic-501",
    ) == 0
    req = _CAPTURED[-1]
    assert req.function == "conduct.epic_task.update_status"
    assert req.target.task_num == 3
    assert req.payload == {
        "status": "implementing",
        "note": "retry",
        "no_rebuild": True,
        "no_github": False,
        "no_derive": False,
        "claim_bypass": "simulation-autofix:epic-501",
    }


def test_conduct_proceed_handoff_splits_ticket_ids() -> None:
    assert _run(
        "conduct", "epic", "proceed-triage-handoff",
        "--epic", "501", "--recommendation", "PROCEED",
        "--gap-summary", "minor", "--filed-tickets", "YOK-1,YOK-2",
    ) == 0
    req = _CAPTURED[-1]
    assert req.function == "conduct.epic.proceed_triage_handoff"
    assert req.target.epic_id == 501
    assert req.payload == {
        "recommendation": "PROCEED",
        "gap_summary": "minor",
        "filed_ticket_ids": ["YOK-1", "YOK-2"],
        "session_id": None,
    }
