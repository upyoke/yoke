"""Dispatch-path tests for the dispatcher-backed ``yoke workflow-item epic-task``
subcommands: review-seed / review-insert / review-get / review-list /
body-get / update-status / simulation-upsert / submission-receipt-get."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_epic_review_test_support import (
    _CAPTURED_REQUESTS as _CAPTURED_REQUESTS,
    _reset_captured as _reset_captured,
    _run as _run,
    _run_capture as _run_capture,
    _stub_ok as _stub_ok,
)


from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
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


class TestReviewSeed:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-seed",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.review_seed"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num == 3
        assert req.payload == {}

    def test_missing_task_num_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-seed",
            "--epic",
            "YOK-501",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestReviewInsert:
    def test_dispatches_and_lowercases_verdict(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-insert",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--verdict",
            "PASS",
            "--head-sha",
            "a" * 40,
            "--body",
            "looks good",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.review_insert"
        assert req.payload == {
            "verdict": "pass",
            "body": "looks good",
            "head_sha": "a" * 40,
        }

    def test_invalid_verdict_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-insert",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--verdict",
            "maybe",
            "--body",
            "x",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_body_file_reads_path(self, tmp_path) -> None:
        body_file = tmp_path / "review.md"
        body_file.write_text("verdict body from file", encoding="utf-8")
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-insert",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--verdict",
            "fail",
            "--body-file",
            str(body_file),
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "verdict": "fail",
            "body": "verdict body from file",
        }


class TestReviewGet:
    def test_dispatches_and_prints_review_row(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "epic_id": 501,
                    "task_num": 3,
                    "review": "9|501|3|PASS|Good|2026-01-01T00:00:00Z",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "workflow-item",
            "epic-task",
            "review-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 0
        assert out == "9|501|3|PASS|Good|2026-01-01T00:00:00Z\n"
        assert _CAPTURED_REQUESTS[-1].function == "workflow_item.epic_task.review_get"

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail,
            "workflow-item",
            "epic-task",
            "review-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 1


class TestReviewList:
    def test_dispatches_with_limit(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "review-list",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--limit",
            "5",
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
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={"epic_id": 501, "task_num": 3, "body": "the body"},
            )

        rc, out, _err = _run_capture(
            stub,
            "workflow-item",
            "epic-task",
            "body-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 0
        assert out == "the body\n"
        assert _CAPTURED_REQUESTS[-1].function == "workflow_item.epic_task.body_get"

    def test_output_file_writes_body_to_path(self, tmp_path) -> None:
        target = tmp_path / "task-body.md"

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={"epic_id": 501, "task_num": 3, "body": "file body"},
            )

        rc, out, _err = _run_capture(
            stub,
            "workflow-item",
            "epic-task",
            "body-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--output-file",
            str(target),
        )
        assert rc == 0
        assert out == ""
        assert target.read_text(encoding="utf-8") == "file body"

    def test_output_file_with_json_returns_two(self, tmp_path) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "body-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--output-file",
            str(tmp_path / "x.md"),
            "--json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestUpdateStatus:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "update-status",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--status",
            "planned",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.update_status"
        assert req.payload == {"status": "planned"}

    def test_missing_status_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "update-status",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 2
