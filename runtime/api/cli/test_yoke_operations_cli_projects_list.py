"""Dispatch-path tests for ``yoke projects list``."""

from __future__ import annotations

import pytest

from runtime.api.cli.yoke_operations_cli_projects_test_support import (_CAPTURED_REQUESTS, _stub_ok)
from runtime.api.cli.yoke_operations_cli_epic_task_test_support import (_run)
from runtime.api.cli.yoke_operations_cli_epic_review_test_support import (_run_capture)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestProjectsList:

    def test_dispatches_empty_payload(self) -> None:
        rc = _run(_stub_ok, "projects", "list")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.list"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_prints_pipe_rows_with_header(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "fields": [
                        "id",
                        "slug",
                        "name",
                        "default_branch",
                        "created_at",
                    ],
                    "rows": [
                        {
                            "id": 1,
                            "slug": "yoke",
                            "name": "Yoke",
                            "default_branch": "main",
                            "created_at": "2026-01-01T00:00:00.000000Z",
                        },
                    ],
                },
            )

        rc, out, _err = _run_capture(stub, "projects", "list")
        assert rc == 0
        assert "id | slug | name | default branch | created at" in out
        assert "1 | yoke | Yoke | main | 2026-01-01T00:00:00.000000Z" in out

    def test_prints_header_and_empty_state(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "fields": [
                        "id",
                        "slug",
                        "name",
                        "default_branch",
                        "created_at",
                    ],
                    "rows": [],
                },
            )

        rc, out, _err = _run_capture(stub, "projects", "list")
        assert rc == 0
        assert "rows: no entries." in out
