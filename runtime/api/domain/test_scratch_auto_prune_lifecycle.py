"""Automatic scratch pruning rides the stale-session lifecycle sweep."""

from __future__ import annotations

from runtime.api import sessions_api_stale_test_helpers as stale_helpers
from yoke_core.domain import sessions_cleanup
from yoke_core.domain.scratch_auto_prune import ScratchPruneResult


conn_fixture = stale_helpers.conn


def test_stale_session_sweep_runs_throttled_scratch_pruner(
    conn_fixture, monkeypatch
):
    calls = []

    def fake_prune(bound_conn):
        calls.append(bound_conn)
        return ScratchPruneResult(removed_count=2, protected_run_count=3)

    monkeypatch.setattr(sessions_cleanup, "auto_prune_stale_scratch", fake_prune)

    result = sessions_cleanup.clean_stale_harness_sessions(conn_fixture)

    assert calls == [conn_fixture]
    assert result["scratch_cleanup"] == {
        "stale_count": 0,
        "removed_count": 2,
        "failure_count": 0,
        "protected_run_count": 3,
        "skipped_throttle": False,
        "registry_error": "",
    }
