"""Events adapters attach the checkout's mapped project client-side."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


def test_events_tail_attaches_cwd_project() -> None:
    with patch(
        "yoke_cli.commands.adapters.events.client_project_context",
        return_value="yoke",
    ):
        rc = _run_with_dispatch(_stub_dispatch_ok, "events", "tail", "--limit", "5")
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "events.tail.run"
    assert req.payload["project"] == "yoke"
    assert req.target.project_id == "yoke"


def test_events_query_attaches_cwd_project() -> None:
    with patch(
        "yoke_cli.commands.adapters.events_query_filters.client_project_context",
        return_value="yoke",
    ):
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "events",
            "query",
            "--limit",
            "10",
        )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "events.query.run"
    assert req.payload["project"] == "yoke"
    assert req.target.project_id == "yoke"


def test_events_emit_attaches_cwd_project() -> None:
    with patch(
        "yoke_cli.commands.adapters.events.client_project_context",
        return_value="yoke",
    ):
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "events",
            "emit",
            "--name",
            "TestEvent",
            "--kind",
            "system",
            "--type",
            "test",
            "--source-type",
            "system",
        )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "events.emit"
    assert req.payload["project"] == "yoke"
    assert req.target.project_id == "yoke"


def test_event_emit_keeps_the_public_item_selector():
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "events",
        "emit",
        "--name",
        "TestEvent",
        "--kind",
        "system",
        "--type",
        "test",
        "--source-type",
        "system",
        "--item",
        "ITEM-7",
    )
    assert rc == 0
    payload = _CAPTURED_REQUESTS[-1].payload
    assert payload["public_ref"] == "ITEM-7"
    assert "item_id" not in payload


def test_event_emit_refuses_numeric_item_before_dispatch():
    before = len(_CAPTURED_REQUESTS)
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "events",
        "emit",
        "--name",
        "TestEvent",
        "--kind",
        "system",
        "--type",
        "test",
        "--source-type",
        "system",
        "--item",
        "7",
        "--project",
        "yoke",
    )
    assert rc == 1
    assert len(_CAPTURED_REQUESTS) == before
