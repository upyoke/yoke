"""Dispatch tests for project_structure command_definitions read wrappers."""

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


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    rc, _out, _err = _run_capture(stub, *argv, session_id=session_id)
    return rc


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


class TestProjectStructureCommandDefinitions:
    def test_get_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[
            ("project-structure", "command-definitions", "get")
        ][0] == "project_structure.command_definitions.get"

    def test_list_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[
            ("project-structure", "command-definitions", "list")
        ][0] == "project_structure.command_definitions.list"

    def test_deploy_defaults_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[
            ("project-structure", "deploy-defaults", "get")
        ][0] == "project_structure.deploy_defaults.get"

    def test_get_dispatches_project_and_scope(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure", "command-definitions", "get",
            "--project", "yoke",
            "--scope", "quick",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "project_structure.command_definitions.get"
        assert req.target.kind == "project_structure"
        assert req.target.project_id == "yoke"
        assert req.payload == {"project_id": "yoke", "scope": "quick"}

    def test_get_prints_command_value(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project_id": "yoke",
                    "scope": "quick",
                    "command": "pytest -q",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "project-structure", "command-definitions", "get",
            "--project", "yoke",
            "--scope", "quick",
        )
        assert rc == 0
        assert out == "pytest -q\n"

    def test_get_absent_command_prints_empty_stdout(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project_id": "yoke",
                    "scope": "quick",
                    "command": None,
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "project-structure", "command-definitions", "get",
            "--project", "yoke",
            "--scope", "quick",
        )
        assert rc == 0
        assert out == ""

    def test_list_dispatches_project(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure", "command-definitions", "list",
            "--project", "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "project_structure.command_definitions.list"
        assert req.target.kind == "project_structure"
        assert req.target.project_id == "yoke"
        assert req.payload == {"project_id": "yoke"}

    def test_list_prints_scope_command_lines(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project_id": "yoke",
                    "commands": {
                        "quick": "pytest -q",
                        "full": "pytest",
                    },
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "project-structure", "command-definitions", "list",
            "--project", "yoke",
        )
        assert rc == 0
        assert out == "quick=pytest -q\nfull=pytest\n"

    def test_deploy_defaults_get_dispatches_project(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure", "deploy-defaults", "get",
            "--project", "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "project_structure.deploy_defaults.get"
        assert req.target.kind == "project_structure"
        assert req.target.project_id == "yoke"
        assert req.payload == {"project_id": "yoke"}

    def test_deploy_defaults_get_prints_default_flow(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project_id": "yoke",
                    "deployment_flow": "yoke-prod-release",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "project-structure", "deploy-defaults", "get",
            "--project", "yoke",
        )
        assert rc == 0
        assert out == "yoke-prod-release\n"

    def test_deploy_defaults_get_absent_default_prints_empty_stdout(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project_id": "yoke",
                    "deployment_flow": None,
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "project-structure", "deploy-defaults", "get",
            "--project", "yoke",
        )
        assert rc == 0
        assert out == ""
