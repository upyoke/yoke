"""Dispatch-path tests for ``yoke workflow-item epic-task ...``,
``yoke workflow-item epic-progress-note ...``, and ``yoke epic-tasks list``."""

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
    FunctionError,
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


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="target_not_found", message="stub"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    rc, _out, _err = _run_capture(stub, *argv, session_id=session_id)
    return rc


def _run_capture(
    stub,
    *argv: str,
    session_id: str = "test-session",
) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(list(argv))
                return rc, out.getvalue(), err.getvalue()


class TestEpicTaskBodyReplace:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "body-replace",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--body",
            "new task body",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.body_replace"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num == 3
        assert req.payload == {"body": "new task body"}


class TestEpicTaskSplit:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "split",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--children-json",
            '[{"title":"Child A"},{"title":"Child B"}]',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.split"
        assert req.payload == {
            "children": [{"title": "Child A"}, {"title": "Child B"}],
        }

    def test_bad_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "split",
            "--epic",
            "YOK-1",
            "--task-num",
            "1",
            "--children-json",
            "{not-json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestEpicTaskReassign:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "reassign",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--new-worktree",
            "YOK-501-new",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.reassign"
        assert req.payload == {"new_worktree": "YOK-501-new"}


class TestEpicTaskAdd:
    def test_dispatches_minimal(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "add",
            "--epic",
            "YOK-501",
            "--title",
            "New task",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.add"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num is None
        assert req.payload == {
            "title": "New task",
            "body": "",
            "worktree": "",
            "context_estimate": "",
            "dependencies": "",
        }

    def test_dispatches_with_metadata(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "add",
            "--epic",
            "YOK-501",
            "--title",
            "Task X",
            "--body",
            "task body",
            "--worktree",
            "YOK-501-X",
            "--context-estimate",
            "2-3 sessions",
            "--dependencies",
            "1,2",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "title": "Task X",
            "body": "task body",
            "worktree": "YOK-501-X",
            "context_estimate": "2-3 sessions",
            "dependencies": "1,2",
        }


class TestEpicTaskRemove:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "remove",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--reason",
            "obsolete",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.remove"
        assert req.payload == {"reason": "obsolete"}


class TestEpicTaskMetadataUpdate:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "metadata-update",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--fields-json",
            '{"status":"in_progress","worktree":"YOK-501-3"}',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.metadata_update"
        assert req.payload == {
            "fields": {"status": "in_progress", "worktree": "YOK-501-3"},
        }

    def test_bad_fields_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "metadata-update",
            "--epic",
            "YOK-1",
            "--task-num",
            "1",
            "--fields-json",
            "[]",
        )
        assert rc == 2


class TestEpicProgressNote:
    def test_append_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-progress-note",
            "append",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--note-num",
            "1",
            "--body",
            "kickoff",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_progress_note.append"
        assert req.payload == {
            "note_num": 1,
            "body": "kickoff",
            "commit_hash": "",
        }

    def test_list_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-progress-note",
            "list",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--limit",
            "10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_progress_note.list"
        assert req.payload == {"limit": 10}
