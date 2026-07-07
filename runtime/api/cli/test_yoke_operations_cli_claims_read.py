"""Dispatch-path tests for ``yoke claims work holder-{get,list}`` and
``yoke path-claims conflicts list``."""

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
        error=FunctionError(code="invalid_payload", message="stub failure"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


class TestClaimsWorkHolderGet:
    def test_dispatches_with_item_payload(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "holder-get", "1818")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.holder_get"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1818"
        assert req.payload == {}

    def test_item_flag_form_dispatches(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "holder-get", "--item", "1818")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.holder_get"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1818"
        assert req.payload == {}

    def test_missing_item_returns_usage_error(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "holder-get")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_bad_ref_relays_verbatim(self) -> None:
        # Relay contract: ref validation is server-side.
        rc = _run(_stub_ok, "claims", "work", "holder-get", "not-a-sun-id")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.item_ref == "not-a-sun-id"


class TestClaimsWorkCurrent:
    """``yoke claims work current`` alias dispatches via holder_get."""

    def test_flag_form_dispatches(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "current", "--item", "1880")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.holder_get"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1880"
        assert req.payload == {}

    def test_positional_form_dispatches(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "current", "1880")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.holder_get"
        assert req.target.item_ref == "1880"

    def test_missing_item_returns_usage_error(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "current")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestClaimsWorkHolderList:
    def test_item_filter_dispatches(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "holder-list", "--item", "1818")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.holder_list"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1818"
        assert req.payload == {}

    def test_session_filter_dispatches_global(self) -> None:
        rc = _run(
            _stub_ok, "claims", "work", "holder-list",
            "--session-id-filter", "abc-123",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "global"
        assert req.payload == {"session_id": "abc-123"}

    def test_no_filter_returns_two(self) -> None:
        rc = _run(_stub_ok, "claims", "work", "holder-list")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestPathClaimsConflictsList:
    def test_no_filters_dispatches_global(self) -> None:
        rc = _run(_stub_ok, "path-claims", "conflicts", "list")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "path_claims.conflicts.list"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_integration_target_filter_propagates(self) -> None:
        rc = _run(
            _stub_ok, "path-claims", "conflicts", "list",
            "--integration-target", "main",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload == {"integration_target": "main"}
        assert req.target.kind == "global"

    def test_item_filter_dispatches_item_scoped(self) -> None:
        rc = _run(_stub_ok, "path-claims", "conflicts", "list", "--item", "7")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "item"
        assert req.target.item_ref == "7"

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(_stub_fail, "path-claims", "conflicts", "list")
        assert rc == 1
