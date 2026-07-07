"""Dispatch-path tests for ``yoke db-claim amend``."""

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
        error=FunctionError(code="amend_failed", message="stub"),
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


class TestDbClaimAmendDispatch:
    def test_state_none_alias_dispatches(self) -> None:
        rc = _run(
            _stub_ok, "db-claim", "amend", "42",
            "--reason", "no governed work", "--state", "none",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "db_claim.amend"
        assert req.target.kind == "item"
        assert req.target.item_ref == "42"
        assert req.payload == {
            "claim": {"state": "none"},
            "reason": "no governed work",
        }

    def test_payload_json_dispatches(self) -> None:
        rc = _run(
            _stub_ok, "db-claim", "amend", "7",
            "--reason", "declare profile",
            "--payload", '{"state":"declared","migration_strategy":"additive_only"}',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["claim"] == {
            "state": "declared", "migration_strategy": "additive_only",
        }
        assert req.payload["reason"] == "declare profile"


class TestDbClaimAmendErrors:
    def test_missing_payload_selector_returns_two(self) -> None:
        rc = _run(_stub_ok, "db-claim", "amend", "42", "--reason", "x")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_reason_returns_two(self) -> None:
        rc = _run(_stub_ok, "db-claim", "amend", "42", "--state", "none")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_bad_payload_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "db-claim", "amend", "42",
            "--reason", "x", "--payload", "{ not json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_non_object_payload_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "db-claim", "amend", "42",
            "--reason", "x", "--payload", '[1, 2, 3]',
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail, "db-claim", "amend", "42",
            "--reason", "x", "--state", "none",
        )
        assert rc == 1
