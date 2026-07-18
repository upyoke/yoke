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
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
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
            _stub_ok, "projects", "get",
            "--project", "yoke", "--field", "default_branch",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "project": "yoke", "field": "default_branch",
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
            stub, "projects", "get",
            "--project", "yoke", "--field", "default_branch",
        )
        assert rc == 0
        assert out == "main\n"

    def test_missing_project_returns_two(self) -> None:
        rc = _run(_stub_ok, "projects", "get")
        assert rc == 2


class TestProjectsList:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_REGISTRY,
        )

        assert SUBCOMMAND_REGISTRY[("projects", "list")][0] == "projects.list"

    def test_dispatches_empty_payload(self) -> None:
        rc = _run(_stub_ok, "projects", "list")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.list"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_prints_pipe_rows(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "fields": [
                        "id", "slug", "name",
                        "default_branch", "created_at",
                    ],
                    "rows": [
                        {
                            "id": "1",
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
        assert out == "1|yoke|Yoke|main|2026-01-01\n"


class TestProjectsResolveByGithubRepo:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[
            ("projects", "resolve-by-github-repo")
        ][0] == "projects.resolve_by_github_repo"

    def test_dispatches_github_repo_payload(self) -> None:
        rc = _run(
            _stub_ok,
            "projects", "resolve-by-github-repo",
            "--github-repo", "example-org/externalwebapp",
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
            _stub_ok, "projects", "capability", "has",
            "--project", "yoke", "--cap-type", "deployment",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.capability.has"
        assert req.payload == {"project": "yoke", "cap_type": "deployment"}

    def test_missing_cap_type_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "projects", "capability", "has", "--project", "yoke",
        )
        assert rc == 2


class TestProjectsCheckoutContext:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_REGISTRY,
        )

        assert SUBCOMMAND_REGISTRY[("projects", "checkout-context")][0] == (
            "projects.checkout_context.run"
        )

    def test_dispatches_empty_payload_global_target(self) -> None:
        rc = _run(_stub_ok, "projects", "checkout-context")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.checkout_context.run"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_explicit_project_rides_on_target(self) -> None:
        rc = _run(
            _stub_ok, "projects", "checkout-context", "--project", "externalwebapp",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.project_id == "externalwebapp"

    def test_env_project_used_when_no_flag(self) -> None:
        with patch.dict("os.environ", {"YOKE_PROJECT": "2"}):
            rc = _run(_stub_ok, "projects", "checkout-context")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.project_id == "2"

    def test_adapter_is_db_free_pre_dispatch(self) -> None:
        """https-transport shape: envelope construction never opens a
        client DB connection — the dispatch seam is the only authority."""

        def _no_client_db(*args, **kwargs):
            raise AssertionError(
                "client DB connection attempted pre-dispatch"
            )

        with patch(
            "yoke_core.domain.db_backend.connect",
            side_effect=_no_client_db,
        ):
            rc = _run(
                _stub_ok, "projects", "checkout-context",
                "--project", "externalwebapp", "--field", "slug",
            )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].function == (
            "projects.checkout_context.run"
        )

    def _identity_stub(self, request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id,
            result={
                "id": 2, "slug": "externalwebapp", "name": "ExternalWebapp",
                "public_item_prefix": "EXT",
            },
        )

    def test_field_projection_prints_bare_value(self) -> None:
        rc, out, _err = _run_capture(
            self._identity_stub, "projects", "checkout-context",
            "--project", "externalwebapp", "--field", "slug",
        )
        assert rc == 0
        assert out == "externalwebapp\n"

    def test_no_field_prints_pipe_row(self) -> None:
        rc, out, _err = _run_capture(
            self._identity_stub, "projects", "checkout-context",
            "--project", "externalwebapp",
        )
        assert rc == 0
        assert out == "2|externalwebapp|ExternalWebapp|EXT\n"

    def test_unknown_field_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "projects", "checkout-context", "--field", "made_up",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail, "projects", "checkout-context", "--project", "externalwebapp",
        )
        assert rc == 1


class TestProjectStructurePatchApply:
    def test_dispatches(self) -> None:
        rc = _run(
            _stub_ok, "project-structure", "patch", "apply",
            "--project", "yoke",
            "--ops-json", '[{"op":"replace","path":"/foo","value":"bar"}]',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "project_structure.patch.apply"
        assert req.payload == {
            "project_id": "yoke",
            "ops": [{"op": "replace", "path": "/foo", "value": "bar"}],
        }

    def test_with_actor_override(self) -> None:
        rc = _run(
            _stub_ok, "project-structure", "patch", "apply",
            "--project", "yoke",
            "--ops-json", "[]",
            "--actor", "ops@example.com",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["actor"] == "ops@example.com"

    def test_bad_ops_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "project-structure", "patch", "apply",
            "--project", "yoke", "--ops-json", "{not-json",
        )
        assert rc == 2

    def test_non_array_ops_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "project-structure", "patch", "apply",
            "--project", "yoke", "--ops-json", '{"foo": 1}',
        )
        assert rc == 2

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail, "project-structure", "patch", "apply",
            "--project", "yoke", "--ops-json", "[]",
        )
        assert rc == 1
