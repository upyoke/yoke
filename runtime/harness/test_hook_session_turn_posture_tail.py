"""Aggregate hook-tail persistence coverage for native turn posture."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

from yoke_core.hooks.run_tail import flush_run_tail
from yoke_core.hooks.session_turn_posture_tail import (
    persist_accepted_hook_turn_posture,
)


OBSERVED = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)


def _seed(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE harness_sessions ("
        "session_id TEXT PRIMARY KEY,"
        "turn_posture TEXT NOT NULL DEFAULT 'unknown',turn_posture_at TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('s1','running',NULL)")
    conn.commit()
    conn.close()


def test_accepted_stop_commits_waiting_posture(tmp_path) -> None:
    path = tmp_path / "posture.sqlite"
    _seed(path)

    assert persist_accepted_hook_turn_posture(
        event_name="Stop",
        session_id="s1",
        observed_at=OBSERVED,
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=lambda: sqlite3.connect(path),
    )

    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT turn_posture,turn_posture_at FROM harness_sessions"
    ).fetchone() == ("waiting", "2026-08-23T13:00:00.000000Z")
    conn.close()


def test_denied_or_failed_stop_never_opens_a_connection() -> None:
    def forbidden_connection():
        raise AssertionError("posture persistence should have been skipped")

    for outcome, failed in (("deny", False), ("allow", True)):
        assert not persist_accepted_hook_turn_posture(
            event_name="Stop",
            session_id="s1",
            observed_at=OBSERVED,
            final_outcome=outcome,
            timed_out=False,
            failed=failed,
            connection_factory=forbidden_connection,
        )


def test_run_tail_passes_aggregate_failure_to_posture_persistence(
    monkeypatch,
) -> None:
    captured = []
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.flush_hook_telemetry",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **kwargs: captured.append(kwargs),
    )
    context = SimpleNamespace(
        executor_family="codex",
        session_id="s1",
        item_id=None,
        tool_name="",
        now=OBSERVED,
    )
    deadline = SimpleNamespace(telemetry_allowed=lambda: True, budget_ms=1000)

    flush_run_tail(
        event_name="Stop",
        context=context,
        chain_length=1,
        final_outcome="allow",
        hook_wait_ms=2,
        timed_out=False,
        deadline=deadline,
        payload={},
        stdin_data="",
        controls=None,
        telem_records=[("failed", {"failure": "exception_RuntimeError"})],
    )

    assert captured[0]["failed"] is True
