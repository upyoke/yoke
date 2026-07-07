"""Dispatch-path tests for the dispatcher-backed ``yoke workflow-item epic-task``
subcommands: review-seed / review-insert / review-get / review-list /
body-get / update-status / simulation-upsert / submission-receipt-get."""

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
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="target_not_found", message="stub"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_capture(
    stub, *argv: str, session_id: str = "test-session",
) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
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
                    rc = cli_main(list(argv))
                return rc, out.getvalue(), err.getvalue()


def _run(stub, *argv: str) -> int:
    rc, _out, _err = _run_capture(stub, *argv)
    return rc


class TestReviewSeed:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-seed",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.review_seed"
        assert req.target.kind == "epic_task"
        assert req.target.epic_id == 501
        assert req.target.task_num == 3
        assert req.payload == {}

    def test_missing_task_num_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-seed",
            "--epic", "501",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestReviewInsert:
    def test_dispatches_and_lowercases_verdict(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-insert",
            "--epic", "501", "--task-num", "3",
            "--verdict", "PASS", "--body", "looks good",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.review_insert"
        assert req.payload == {"verdict": "pass", "body": "looks good"}

    def test_invalid_verdict_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-insert",
            "--epic", "501", "--task-num", "3",
            "--verdict", "maybe", "--body", "x",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_body_file_reads_path(self, tmp_path) -> None:
        body_file = tmp_path / "review.md"
        body_file.write_text("verdict body from file", encoding="utf-8")
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-insert",
            "--epic", "501", "--task-num", "3",
            "--verdict", "fail", "--body-file", str(body_file),
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "verdict": "fail", "body": "verdict body from file",
        }


class TestReviewGet:
    def test_dispatches_and_prints_review_row(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={
                    "epic_id": 501, "task_num": 3,
                    "review": "9|501|3|PASS|Good|2026-01-01T00:00:00Z",
                },
            )

        rc, out, _err = _run_capture(
            stub, "workflow-item", "epic-task", "review-get",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 0
        assert out == "9|501|3|PASS|Good|2026-01-01T00:00:00Z\n"
        assert _CAPTURED_REQUESTS[-1].function == "workflow_item.epic_task.review_get"

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail, "workflow-item", "epic-task", "review-get",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 1


class TestReviewList:
    def test_dispatches_with_limit(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "review-list",
            "--epic", "501", "--task-num", "3", "--limit", "5",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.review_list"
        assert req.payload == {"limit": 5}


class TestBodyGet:
    def test_dispatches_and_prints_body(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={"epic_id": 501, "task_num": 3, "body": "the body"},
            )

        rc, out, _err = _run_capture(
            stub, "workflow-item", "epic-task", "body-get",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 0
        assert out == "the body\n"
        assert _CAPTURED_REQUESTS[-1].function == "workflow_item.epic_task.body_get"

    def test_output_file_writes_body_to_path(self, tmp_path) -> None:
        target = tmp_path / "task-body.md"

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={"epic_id": 501, "task_num": 3, "body": "file body"},
            )

        rc, out, _err = _run_capture(
            stub, "workflow-item", "epic-task", "body-get",
            "--epic", "501", "--task-num", "3", "--output-file", str(target),
        )
        assert rc == 0
        assert out == ""
        assert target.read_text(encoding="utf-8") == "file body"

    def test_output_file_with_json_returns_two(self, tmp_path) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "body-get",
            "--epic", "501", "--task-num", "3",
            "--output-file", str(tmp_path / "x.md"), "--json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestUpdateStatus:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "update-status",
            "--epic", "501", "--task-num", "3", "--status", "planned",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.update_status"
        assert req.payload == {"status": "planned"}

    def test_missing_status_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "update-status",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 2


class TestSimulationUpsert:
    def test_dispatches_epic_level_target(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "simulation-upsert",
            "--epic", "501", "--phase", "plan",
            "--body", "SIMULATION: CLEAN",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.simulation_upsert"
        assert req.target.kind == "epic_task"
        assert req.target.epic_id == 501
        assert req.target.task_num is None
        assert req.payload == {"phase": "plan", "body": "SIMULATION: CLEAN"}

    def test_missing_body_source_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "simulation-upsert",
            "--epic", "501", "--phase", "plan",
        )
        assert rc == 2


class TestSubmissionReceiptGet:
    def test_dispatches_with_watermark(self) -> None:
        rc = _run(
            _stub_ok, "workflow-item", "epic-task", "submission-receipt-get",
            "--epic", "501", "--task-num", "3", "--after-note-count", "2",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.submission_receipt_get"
        assert req.payload == {"after_note_count": 2}

    def test_prints_receipt_line(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={
                    "epic_id": 501, "task_num": 3,
                    "receipt": "PASS|501|3|4|abc123|2026-01-01|test_plan=PASS",
                },
            )

        rc, out, _err = _run_capture(
            stub, "workflow-item", "epic-task", "submission-receipt-get",
            "--epic", "501", "--task-num", "3",
        )
        assert rc == 0
        assert out == "PASS|501|3|4|abc123|2026-01-01|test_plan=PASS\n"
