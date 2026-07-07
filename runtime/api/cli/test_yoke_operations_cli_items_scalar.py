"""Dispatch-path tests for ``yoke items scalar update``.

Covers the ``items.scalar.update`` flag adapter — happy paths for the
three value selectors (``--value`` string, ``--null``, ``--value-json``),
the four bool/internal flags (``--force``, ``--qa-bypass``,
``--done-nonce-verified``), one usage-error path per failure mode, and
dispatch-failure exit-code propagation.
"""

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


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "item_id": request.target.item_id,
            "field": request.payload.get("field"),
            "value": request.payload.get("value"),
        },
    )


def _stub_dispatch_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="frozen", message="item is frozen"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_with_dispatch(stub, *argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                buf = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(err):
                    return cli_main(list(argv))


class TestItemsScalarUpdateDispatch:
    def test_string_value_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "42",
            "--field", "priority", "--value", "high",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.scalar.update"
        assert req.target.kind == "item"
        assert req.target.item_ref == "42"
        assert req.payload == {
            "field": "priority",
            "value": "high",
            "done_nonce_verified": False,
            "force": False,
            "qa_bypass": False,
        }
        assert req.actor.session_id == "test-session"

    def test_null_value_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "100",
            "--field", "worktree", "--null",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["field"] == "worktree"
        assert req.payload["value"] is None

    def test_value_json_dispatches_with_typed_payload(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "101",
            "--field", "blocked", "--value-json", "true",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["field"] == "blocked"
        assert req.payload["value"] is True

    def test_force_and_qa_bypass_flags_propagate(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "200",
            "--field", "frozen", "--value", "false",
            "--force", "--qa-bypass",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["force"] is True
        assert req.payload["qa_bypass"] is True
        assert req.payload["done_nonce_verified"] is False

    def test_done_nonce_verified_flag_propagates(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "201",
            "--field", "status", "--value", "done",
            "--done-nonce-verified",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["done_nonce_verified"] is True


class TestItemsScalarUpdateErrors:
    def test_missing_value_selector_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "42", "--field", "priority",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_two_value_selectors_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "42",
            "--field", "priority", "--value", "high", "--null",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_field_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "42", "--value", "high",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_bad_ref_relays_verbatim(self) -> None:
        # Relay contract: ref validation is server-side.
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "not-a-sun-id",
            "--field", "priority", "--value", "high",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.item_ref == "not-a-sun-id"

    def test_bad_value_json_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "scalar", "update", "42",
            "--field", "blocked", "--value-json", "{ not valid json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_fail,
            "items", "scalar", "update", "42",
            "--field", "priority", "--value", "high",
        )
        assert rc == 1
