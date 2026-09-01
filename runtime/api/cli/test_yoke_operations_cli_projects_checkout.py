"""Dispatch-path tests for ``yoke projects checkout-context``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.cli.test_yoke_operations_cli_projects import (
    _CAPTURED_REQUESTS,
    _run,
    _run_capture,
    _stub_fail,
    _stub_ok,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestProjectsCheckoutContext:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

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
            _stub_ok,
            "projects",
            "checkout-context",
            "--project",
            "externalwebapp",
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
            raise AssertionError("client DB connection attempted pre-dispatch")

        with patch(
            "yoke_core.domain.db_backend.connect",
            side_effect=_no_client_db,
        ):
            rc = _run(
                _stub_ok,
                "projects",
                "checkout-context",
                "--project",
                "externalwebapp",
                "--field",
                "slug",
            )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].function == "projects.checkout_context.run"

    def _identity_stub(self, request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "id": 2,
                "slug": "externalwebapp",
                "name": "ExternalWebapp",
                "public_item_prefix": "EXT",
            },
        )

    def test_field_projection_prints_bare_value(self) -> None:
        rc, out, _err = _run_capture(
            self._identity_stub,
            "projects",
            "checkout-context",
            "--project",
            "externalwebapp",
            "--field",
            "slug",
        )
        assert rc == 0
        assert out == "externalwebapp\n"

    def test_no_field_prints_pipe_row(self) -> None:
        rc, out, _err = _run_capture(
            self._identity_stub,
            "projects",
            "checkout-context",
            "--project",
            "externalwebapp",
        )
        assert rc == 0
        assert out == "2|externalwebapp|ExternalWebapp|EXT\n"

    def test_unknown_field_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "projects",
            "checkout-context",
            "--field",
            "made_up",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail,
            "projects",
            "checkout-context",
            "--project",
            "externalwebapp",
        )
        assert rc == 1
