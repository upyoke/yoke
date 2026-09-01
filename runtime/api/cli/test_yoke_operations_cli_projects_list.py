"""Dispatch-path tests for ``yoke projects list``."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_projects import (
    _CAPTURED_REQUESTS,
    _run,
    _run_capture,
    _stub_ok,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestProjectsList:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[("projects", "list")][0] == "projects.list"

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
                            "created_at": "2026-01-01",
                        },
                    ],
                },
            )

        rc, out, _err = _run_capture(stub, "projects", "list")
        assert rc == 0
        assert out == (
            "id|slug|name|default_branch|created_at\n1|yoke|Yoke|main|2026-01-01\n"
        )

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
        assert out == "id|slug|name|default_branch|created_at\n(no projects)\n"
