"""List reads say which part of their output ``--limit`` caps."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _run_capture,
    _stub_dispatch_ok,
)


def _help_text(*argv: str) -> str:
    rc, out, err = _run_capture(_stub_dispatch_ok, *argv, "--help")
    assert rc == 0, err
    return " ".join(out.split())


@pytest.mark.parametrize(
    ("argv", "phrases"),
    [
        (
            ("deployment-runs", "list"),
            ("caps each project's runs", "add --project to cap the total"),
        ),
        (
            ("messages", "list"),
            ("Settled messages per page", "Every actionable message"),
        ),
        (
            ("session-control", "launch", "list"),
            ("Completed-history launches per page", "Every operational launch"),
        ),
        (("items", "overview", "list"), ("The paged read refuses it",)),
    ],
)
def test_limit_help_names_the_part_it_caps(argv, phrases) -> None:
    text = _help_text(*argv)
    for phrase in phrases:
        assert phrase in text


def _tail_reply(result: dict):
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    return stub


def test_tail_refuses_a_server_that_dropped_the_project_filter() -> None:
    rc, out, err = _run_capture(
        _tail_reply({"rows": []}), "events", "tail", "--project", "yoke", "--json"
    )
    assert rc != 0
    assert "events_tail_project_filter_unavailable" in out + err


def test_tail_accepts_the_echoed_project_filter() -> None:
    rc, _out, err = _run_capture(
        _tail_reply({"rows": [], "project": "yoke"}),
        "events",
        "tail",
        "--project",
        "yoke",
    )
    assert rc == 0, err


def test_tail_without_project_flag_keeps_an_older_server_answer() -> None:
    with patch(
        "yoke_cli.commands.adapters.events.client_project_context",
        return_value="yoke",
    ):
        rc, _out, err = _run_capture(_tail_reply({"rows": []}), "events", "tail")
    assert rc == 0, err
