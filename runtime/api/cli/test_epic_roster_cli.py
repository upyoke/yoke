"""Public epic dispatch receipts."""

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_epic_task import (
    _CAPTURED_REQUESTS,
    _stub_ok,
    _stub_fail,
    _run,
    _run_capture,
    _reset_captured as _reset_captured,
)


class TestEpicTasksList:
    def test_dispatches(self) -> None:
        rc = _run(_stub_ok, "epic-tasks", "list", "--epic", "YOK-501")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "epic_tasks.list.run"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.payload == {}

    def test_missing_epic_returns_two(self) -> None:
        rc = _run(_stub_ok, "epic-tasks", "list")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(_stub_fail, "epic-tasks", "list", "--epic", "YOK-999")
        assert rc == 1

    def test_human_output_matches_legacy_rows(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "epic_id": 501,
                    "tasks": [
                        {
                            "task_num": 1,
                            "title": "Plan lane",
                            "status": "planned",
                            "item_worktree_id": 41,
                            "lane": {
                                "id": 41,
                                "branch": "YOK-501-1",
                                "path": "/repo/.worktrees/YOK-501-1",
                                "lane_role": "worker",
                                "state": "active",
                            },
                            "dependencies": "",
                        }
                    ],
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "epic-tasks",
            "list",
            "--epic",
            "YOK-501",
        )
        assert rc == 0
        assert out == "1|Plan lane|planned|YOK-501-1|\n"
