"""Observation math, producer interpretation, and authorization before reads."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.backlog import insert_event
from yoke_core.domain.actor_permissions import PermissionDenied
from yoke_core.domain.performance_metrics import aggregate
from yoke_core.domain.performance_observations import observation, unique_observations
from yoke_core.domain.performance_query import (
    authorized_predicate,
    details,
    read_observations,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def row(**changes):
    return {
        "event_id": "sample",
        "created_at": (NOW - timedelta(hours=1)).isoformat(),
        "event_name": "YokeFunctionCalled",
        "duration_ms": 10,
        "envelope": json.dumps({"context": {"function": "items.list.run"}}),
        **changes,
    }


def test_weighted_average_and_true_bucket_percentile_not_average_of_percentiles():
    values = [
        observation(row(event_id=str(i), duration_ms=ms), NOW)
        for i, ms in enumerate([0] * 99 + [10000])
    ]
    start = values[0]["timestamp"]
    result = aggregate(values, start, start + 60, 20)
    metric = result["buckets"][0]["metrics"]["function"]
    assert metric["count"] == metric["timed_count"] == 100
    assert metric["avg_ms"] == 100
    assert metric["sum_ms"] == 10000
    assert metric["p95_ms"] == 0


def test_nulls_sparse_history_and_zero_preserve_meaning_and_point_budget():
    value = observation(row(duration_ms=None), NOW)
    zero = observation(row(duration_ms=0), NOW)
    start = value["timestamp"]
    result = aggregate([value, zero], start, start + 30 * 86400, 100)
    assert len(result["buckets"]) <= 100
    metric = result["buckets"][0]["metrics"]["function"]
    assert (metric["count"], metric["timed_count"], metric["unknown_count"]) == (
        2,
        1,
        1,
    )
    assert metric["avg_ms"] == 0
    assert result["buckets"][1]["metrics"]["function"]["avg_ms"] is None


@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
def test_owner_timing_repairs_and_deduplicates_all_harnesses(harness):
    end = NOW - timedelta(hours=1)
    source = row(
        event_name="HarnessToolCallCompleted",
        executor=harness,
        duration_ms=None,
        started_at=(end - timedelta(milliseconds=1649)).isoformat(),
        completed_at=end.isoformat(),
        tool_name="Read",
        session_id="session",
        tool_use_id="tool",
    )
    values = unique_observations([source, {**source, "event_id": "duplicate"}], NOW)
    assert len(values) == 1
    assert values[0]["duration_ms"] == 1649
    assert values[0]["timing_status"] == "timed"


def test_semantic_waits_do_not_exclude_slow_bare_shell_and_keep_raw_duration():
    source = row(
        event_name="HarnessToolCallCompleted", duration_ms=2496068, tool_name="Bash"
    )
    bare = observation({**source, "command_summary": "zsh"}, NOW)
    watcher = observation(
        {**source, "command_summary": "yoke --env prod watch deploy -- run-example"},
        NOW,
    )
    relay = observation(
        row(
            envelope=json.dumps(
                {"context": {"function": "session_control.relay.claim"}}
            )
        ),
        NOW,
    )
    assert bare["family"] == "tool"
    assert watcher["family"] == "watcher" and watcher["intentional_wait"]
    assert watcher["duration_ms"] == 2496068
    assert relay["family"] == "relay"


def test_hook_client_wall_contains_evaluator_and_is_never_summed():
    value = observation(
        row(
            event_name="HookDispatchTelemetry",
            hook_event_name="PreToolUse",
            duration_ms=100,
            envelope=json.dumps({"context": {"client_wall_ms": 150}}),
        ),
        NOW,
    )
    assert value["duration_ms"] == 100
    assert value["breakdown"] == {
        "evaluator_ms": 100,
        "client_wall_ms": 150,
        "client_remainder_ms": 50,
    }
    assert value["unavailable_spans"] == []
    assert "Existing owner timings" in value["span_coverage"]


def test_inspection_paginates_ranked_functions_hooks_and_tools_without_sampling():
    values = [observation(row(event_id=str(i), duration_ms=i), NOW) for i in range(120)]
    page = details(values, "function", 0, 50)
    assert page["total"] == 120 and page["next_offset"] == 50
    assert [v["duration_ms"] for v in page["rows"]] == list(range(119, 69, -1))
    assert details(values, "function", 100, 50)["next_offset"] is None


def test_real_permission_scope_excludes_unattributed_and_refuses_forged_project(
    test_db,
):
    auth = mint_api_auth_context(test_db)
    test_db.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (auth.actor_id,))
    test_db.commit()
    predicate, params = authorized_predicate(test_db, str(auth.actor_id), None)
    assert "IS NULL" not in predicate
    assert auth.project_id in params
    with pytest.raises(PermissionDenied, match="performance_scope_denied"):
        authorized_predicate(test_db, str(auth.actor_id), [max(params) + 10000])
    # Current actor grants are evaluated again; no cache carries broader scope.
    test_db.execute(
        "DELETE FROM actor_project_roles WHERE actor_id=%s", (auth.actor_id,)
    )
    test_db.commit()
    predicate, params = authorized_predicate(test_db, str(auth.actor_id), None)
    assert predicate == "FALSE" and not params


def test_time_and_project_predicates_query_entire_range_excluding_other_projects(
    test_db,
):
    auth = mint_api_auth_context(test_db)
    for i, minutes in enumerate([59, 40, 1]):
        insert_event(
            test_db,
            event_id=f"range-{i}",
            event_name="YokeFunctionCalled",
            project_id=auth.project_id,
            duration_ms=i * 100,
            created_at=(NOW - timedelta(minutes=minutes))
            .isoformat()
            .replace("+00:00", "Z"),
        )
    insert_event(
        test_db,
        event_id="unattributed",
        event_name="YokeFunctionCalled",
        project_id=None,
        duration_ms=99999,
        created_at=(NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
    )
    values = read_observations(
        test_db, auth.actor_id, [auth.project_id], NOW - timedelta(hours=1), NOW
    )
    assert {v["event_id"] for v in values} == {"range-0", "range-1", "range-2"}
    assert all(v["project_id"] == auth.project_id for v in values)


def test_budget_refuses_without_partial_success(test_db, monkeypatch):
    import yoke_core.domain.performance_query as query

    monkeypatch.setattr(query, "MAX_OBSERVATIONS", 1)
    for i in range(2):
        insert_event(
            test_db,
            event_id=f"budget-{i}",
            event_name="YokeFunctionCalled",
            duration_ms=10,
            created_at=(NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        )
    with pytest.raises(ValueError, match="No partial aggregate"):
        read_observations(test_db, None, None, NOW - timedelta(hours=1), NOW)
