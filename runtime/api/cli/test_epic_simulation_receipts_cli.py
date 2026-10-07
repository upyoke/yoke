"""Public epic dispatch receipts."""

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_epic_review import (
    _CAPTURED_REQUESTS,
    _stub_ok,
    _run,
    _run_capture,
    _reset_captured as _reset_captured,
)


class TestSimulationUpsert:
    def test_dispatches_epic_level_target(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            "YOK-501",
            "--phase",
            "plan",
            "--body",
            "SIMULATION: CLEAN",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.simulation_upsert"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num is None
        assert req.payload == {"phase": "plan", "body": "SIMULATION: CLEAN"}

    def test_missing_body_source_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            "YOK-501",
            "--phase",
            "plan",
        )
        assert rc == 2


class TestSubmissionReceiptGet:
    def test_dispatches_with_watermark(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "submission-receipt-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--after-note-count",
            "2",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.submission_receipt_get"
        assert req.payload == {"after_note_count": 2}

    def test_prints_receipt_line(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "epic_public_ref": "YOK-501",
                    "task_num": 3,
                    "receipt": "PASS|YOK-501|3|4|abc123|2026-01-01|test_plan=PASS",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "workflow-item",
            "epic-task",
            "submission-receipt-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 0
        assert out == "PASS|YOK-501|3|4|abc123|2026-01-01|test_plan=PASS\n"
