"""The steering report names registered functions over their latency budget."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from runtime.api.fixtures.backlog import insert_event
from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import steering_fleet_report_slow_paths as slow_paths
from yoke_core.domain.steering_fleet_report_compose import (
    combined_body,
    combined_dict,
    compose_held_reports,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest

OVER_BUDGET = "deployment_runs.qa_stage.dispatch"
IN_BUDGET = "items.get.run"
LONG_POLL = "session_control.relay.claim"


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def _call(conn, event_id: str, function: str, duration_ms: int, minutes_ago: int):
    insert_event(
        conn,
        event_id=event_id,
        event_name="YokeFunctionCalled",
        project_id=PROJECT_ID,
        duration_ms=duration_ms,
        envelope=json.dumps({"context": {"function": function}}),
        created_at=parse_instant(NOW) - timedelta(minutes=minutes_ago),
    )


def _seed_calls(conn) -> None:
    _call(conn, "dispatch-slow", OVER_BUDGET, 41_000, 10)
    _call(conn, "dispatch-fast", OVER_BUDGET, 900, 20)
    for index in range(3):
        _call(conn, f"poll-{index}", LONG_POLL, 55_000 + index, 5 + index)
        _call(conn, f"read-{index}", IN_BUDGET, 200 + index, 5 + index)
    # Outside the window: an old slow call no longer counts.
    _call(conn, "read-old", IN_BUDGET, 90_000, 120)


def test_section_lists_an_over_budget_function_only(steering_scope) -> None:
    _seed_calls(steering_scope)

    combined = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    assert [row.operation for row in combined.slow_paths] == [OVER_BUDGET]
    row = combined.slow_paths[0]
    assert (row.count, row.max_ms) == (2, 41_000)
    for text in (combined_body(combined),):
        assert "## slow paths" in text
        assert f"{OVER_BUDGET}  2 calls" in text
        assert "max 41.0s" in text
        assert LONG_POLL not in text
        assert IN_BUDGET not in text
    assert combined_dict(combined)["slow_paths"] == [row.to_dict()]
    assert "## slow paths" not in combined_hook_digest(combined)


def test_p95_over_budget_counts_without_a_single_call_over_the_ceiling() -> None:
    rows = slow_paths.over_budget(
        {
            "family": "function",
            "intentional_wait": False,
            "operation": "charge.schedule",
            "duration_ms": 6_000,
        }
        for _ in range(4)
    )
    assert [(row.operation, row.p95_ms, row.max_ms) for row in rows] == [
        ("charge.schedule", 6_000, 6_000)
    ]


def test_slow_paths_leave_the_report_fingerprint_unchanged(steering_scope) -> None:
    quiet = compose_held_reports(steering_scope, session_id=STEERING_SESSION, now=NOW)
    _seed_calls(steering_scope)
    slow = compose_held_reports(steering_scope, session_id=STEERING_SESSION, now=NOW)

    assert quiet.slow_paths == ()
    assert "## slow paths" not in combined_body(quiet)
    assert quiet.fingerprint() == slow.fingerprint()


def test_unreadable_events_leave_the_section_out(steering_scope, monkeypatch) -> None:
    _seed_calls(steering_scope)
    monkeypatch.setattr(
        slow_paths, "function_identity_sql", lambda column: "no_such_column"
    )

    combined = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    assert combined.slow_paths == ()
    assert "## slow paths" not in combined_body(combined)
    # The failed read rolled back only its own savepoint.
    assert steering_scope.execute("SELECT 1").fetchone()[0] == 1
