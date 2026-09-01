"""Dispatch-path tests for ``yoke projects ...`` and
``yoke project-structure patch apply``."""

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
        error=FunctionError(code="payload_invalid", message="stub"),
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


class TestProjectsGet:
    def test_project_only_dispatches(self) -> None:
        rc = _run(_stub_ok, "projects", "get", "--project", "yoke")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.get"
        assert req.target.kind == "global"
        assert req.payload == {"project": "yoke"}

    def test_with_field_projection(self) -> None:
        rc = _run(
            _stub_ok,
            "projects",
            "get",
            "--project",
            "yoke",
            "--field",
            "default_branch",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "project": "yoke",
            "field": "default_branch",
        }

    def test_field_projection_prints_raw_value(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project": "yoke",
                    "field": "default_branch",
                    "value": "main",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "projects",
            "get",
            "--project",
            "yoke",
            "--field",
            "default_branch",
        )
        assert rc == 0
        assert out == "main\n"

    def test_missing_project_returns_two(self) -> None:
        rc = _run(_stub_ok, "projects", "get")
        assert rc == 2


class TestProjectsResolveByGithubRepo:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert (
            SUBCOMMAND_REGISTRY[("projects", "resolve-by-github-repo")][0]
            == "projects.resolve_by_github_repo"
        )

    def test_dispatches_github_repo_payload(self) -> None:
        rc = _run(
            _stub_ok,
            "projects",
            "resolve-by-github-repo",
            "--github-repo",
            "example-org/externalwebapp",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.resolve_by_github_repo"
        assert req.target.kind == "global"
        assert req.payload == {"github_repo": "example-org/externalwebapp"}

    def test_missing_github_repo_returns_two(self) -> None:
        rc = _run(_stub_ok, "projects", "resolve-by-github-repo")
        assert rc == 2


class TestProjectsCapabilityHas:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok,
            "projects",
            "capability",
            "has",
            "--project",
            "yoke",
            "--cap-type",
            "deployment",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.capability.has"
        assert req.payload == {"project": "yoke", "cap_type": "deployment"}

    def test_missing_cap_type_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "projects",
            "capability",
            "has",
            "--project",
            "yoke",
        )
        assert rc == 2


class TestProjectStructurePatchApply:
    def test_onboarding_shape_dispatches_without_item(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure",
            "patch",
            "apply",
            "--project",
            "yoke",
            "--ops-json",
            '[{"op":"replace","path":"/foo","value":"bar"}]',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "project_structure.patch.apply"
        assert req.target.kind == "project_structure"
        assert req.target.public_ref is None
        assert req.payload == {
            "project_id": "yoke",
            "ops": [{"op": "replace", "path": "/foo", "value": "bar"}],
        }

    def test_with_actor_override(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure",
            "patch",
            "apply",
            "--project",
            "yoke",
            "--item",
            "YOK-2137",
            "--ops-json",
            "[]",
            "--actor",
            "ops@example.com",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.public_ref == "YOK-2137"
        assert _CAPTURED_REQUESTS[-1].payload["actor"] == "ops@example.com"

    def test_bad_ops_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure",
            "patch",
            "apply",
            "--project",
            "yoke",
            "--item",
            "YOK-2137",
            "--ops-json",
            "{not-json",
        )
        assert rc == 2

    def test_non_array_ops_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "project-structure",
            "patch",
            "apply",
            "--project",
            "yoke",
            "--item",
            "YOK-2137",
            "--ops-json",
            '{"foo": 1}',
        )
        assert rc == 2

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail,
            "project-structure",
            "patch",
            "apply",
            "--project",
            "yoke",
            "--item",
            "YOK-2137",
            "--ops-json",
            "[]",
        )
        assert rc == 1
