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
        "yoke_cli.commands.adapters.events.client_project_context",
        return_value="yoke",
    ):
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "events", "query", "--limit", "10",
        )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "events.query.run"
    assert req.payload["project"] == "yoke"
    assert req.target.project_id == "yoke"
