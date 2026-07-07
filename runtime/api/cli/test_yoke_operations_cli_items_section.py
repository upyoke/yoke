"""Dispatch-path tests for ``yoke items section ...`` +
``yoke items structured-field {append-addendum,section-upsert,section-append}``.
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
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_dispatch_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="invalid_payload", message="stub failure"),
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
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


class TestItemsSectionDispatch:
    def test_upsert_dispatches_with_section_target(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "section", "upsert", "42",
            "--section", "Progress Log", "--content", "entry body",
            "--ordering", "200", "--source", "advance",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.section.upsert"
        assert req.target.kind == "section"
        assert req.target.item_ref == "42"
        assert req.target.section_name == "Progress Log"
        assert req.payload == {
            "content": "entry body", "ordering": 200, "source": "advance",
        }

    def test_get_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "section", "get", "99", "--section", "Progress Log",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.section.get"
        assert req.target.kind == "section"
        assert req.target.section_name == "Progress Log"
        assert req.payload == {}

    def test_delete_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "section", "delete", "99", "--section", "Stale Notes",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.section.delete"
        assert req.target.section_name == "Stale Notes"
        assert req.payload == {}


class TestStructuredFieldAdditiveDispatch:
    def test_append_addendum_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "append-addendum", "7",
            "--field", "spec", "--heading", "AC-N: foo",
            "--content", "addendum body", "--source", "refine",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.structured_field.append_addendum"
        assert req.target.kind == "item"
        assert req.target.item_ref == "7"
        assert req.payload == {
            "field": "spec", "heading": "AC-N: foo",
            "content": "addendum body", "source": "refine",
        }

    def test_section_upsert_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "section-upsert", "8",
            "--section", "Findings", "--content", "fresh body",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.structured_field.section_upsert"
        assert req.target.kind == "item"
        assert req.target.item_ref == "8"
        assert req.payload == {"section": "Findings", "content": "fresh body"}

    def test_section_upsert_with_ordering_and_source(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "section-upsert", "8",
            "--section", "Findings", "--content", "fresh body",
            "--ordering", "150", "--source", "refine",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload == {
            "section": "Findings", "content": "fresh body",
            "ordering": 150, "source": "refine",
        }

    def test_section_append_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "section-append", "9",
            "--section", "Progress Log", "--headline", "kickoff",
            "--content", "starting work",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.structured_field.section_append"
        assert req.payload == {
            "section": "Progress Log", "headline": "kickoff",
            "content": "starting work",
        }


class TestErrorShapes:
    def test_section_upsert_missing_content_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "section", "upsert", "42", "--section", "Notes",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_section_get_missing_section_flag_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "section", "get", "42",
        )
        assert rc == 2

    def test_append_addendum_requires_heading(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "append-addendum", "7",
            "--field", "spec", "--content", "body",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_fail,
            "items", "section", "get", "42", "--section", "Notes",
        )
        assert rc == 1
