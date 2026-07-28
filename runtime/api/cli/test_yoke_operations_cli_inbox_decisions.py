"""Dispatch contracts for Inbox inspection and decision resolution."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _run_with_dispatch,
    _stub_dispatch_ok,
)
from yoke_cli.operation_inventory import lookup


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_inbox_list_dispatches_global_with_default_payload() -> None:
    rc = _run_with_dispatch(_stub_dispatch_ok, "inbox", "list")

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "inbox.list"
    assert request.target.kind == "global"
    assert request.payload == {}
    assert request.actor.session_id == "test-session"


def test_inbox_list_dispatches_project_filters_and_read_notifications() -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "inbox",
        "list",
        "--project-id",
        "10",
        "--project-id",
        "42",
        "--include-read",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "inbox.list"
    assert request.payload == {
        "project_ids": [10, 42],
        "include_read": True,
    }


def test_decision_request_resolve_dispatches_action_and_note() -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "decision-requests",
        "resolve",
        "73",
        "waive",
        "--note",
        "physical campaign evidence accepted",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "decision_requests.resolve"
    assert request.target.kind == "global"
    assert request.payload == {
        "request_id": 73,
        "action": "waive",
        "note": "physical campaign evidence accepted",
    }


def test_decision_request_resolve_omits_absent_note() -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "decision-requests",
        "resolve",
        "73",
        "approve",
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "request_id": 73,
        "action": "approve",
    }


def test_decision_request_resolve_rejects_non_integer_request_id() -> None:
    rc, _out, error = _run_capture(
        _stub_dispatch_ok,
        "decision-requests",
        "resolve",
        "not-an-id",
        "approve",
    )

    assert rc == 2
    assert "REQUEST_ID" in error
    assert not _CAPTURED_REQUESTS


@pytest.mark.parametrize(
    ("shell_form", "family"),
    (
        ("yoke inbox list", "inbox"),
        ("yoke decision-requests resolve", "decision_requests"),
    ),
)
def test_operation_inventory_marks_cli_surface_wrapped(
    shell_form: str,
    family: str,
) -> None:
    entry = lookup(shell_form)

    assert entry is not None
    assert entry.status == "wrapped"
    assert entry.family == family
