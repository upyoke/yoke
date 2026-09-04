"""The client wall-time completion is a keyed, bounded, timeout-capped probe.

These pin the contract that replaced the envelope substring scan: the
dispatch row is found by ``events.client_timing_id``, a report with no row
in the window costs one keyed SELECT and nothing else, and every statement
on the connection runs under a per-statement timeout.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog import insert_event
from yoke_core.domain import hook_client_wall
from yoke_core.domain.hook_observation_db_session import (
    HOOK_OBSERVATION_STATEMENT_TIMEOUT_MS,
)


TIMING_ID = "1f8e0a9c-6b74-4a1e-9d2a-2f4c8b6e0a11"


class _RecordingConnection:
    """Delegate to the fixture database while recording every statement."""

    def __init__(self, connection) -> None:
        self.connection = connection
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(" ".join(str(sql).split()))
        return (
            self.connection.execute(sql)
            if params is None
            else self.connection.execute(sql, params)
        )

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self) -> None:
        pass


def _dispatch_envelope(duration_ms: int) -> str:
    return json.dumps(
        {
            "event_name": "HookDispatchTelemetry",
            "duration_ms": duration_ms,
            "context": {
                "hook_wait_ms": duration_ms,
                "client_timing_id": TIMING_ID,
            },
        }
    )


def _recording(monkeypatch, test_db) -> _RecordingConnection:
    recorder = _RecordingConnection(test_db)
    monkeypatch.setattr(hook_client_wall.db_backend, "connect", lambda: recorder)
    monkeypatch.setattr(
        hook_client_wall.db_backend, "connection_is_postgres", lambda _conn: True
    )
    return recorder


def _insert_dispatch(test_db, *, event_id: str, created_at: str | None = None) -> None:
    insert_event(
        test_db,
        event_id=event_id,
        event_name="HookDispatchTelemetry",
        event_type="hook_dispatch",
        source_type="hook",
        duration_ms=40,
        hook_event_name="PreToolUse",
        client_timing_id=TIMING_ID,
        envelope=_dispatch_envelope(40),
        created_at=created_at,
    )


def test_report_finds_its_row_by_key_and_clears_the_correlation(
    test_db, monkeypatch
) -> None:
    recorder = _recording(monkeypatch, test_db)
    _insert_dispatch(test_db, event_id="dispatch-keyed")

    assert hook_client_wall.record_client_wall_reports([(TIMING_ID, 97)]) == 1

    row = test_db.execute(
        "SELECT envelope, client_timing_id FROM events WHERE event_id=%s",
        ("dispatch-keyed",),
    ).fetchone()
    context = json.loads(row[0])["context"]
    assert context["client_wall_ms"] == 97
    assert "client_timing_id" not in context
    # The completed row leaves the partial index, so it stays small.
    assert row[1] is None

    lookup = next(s for s in recorder.statements if s.startswith("SELECT id,"))
    assert "client_timing_id=%s" in lookup
    assert "LIKE" not in "".join(recorder.statements).upper()


def test_absent_row_is_accepted_after_one_keyed_probe(test_db, monkeypatch) -> None:
    recorder = _recording(monkeypatch, test_db)

    assert hook_client_wall.record_client_wall_reports([(TIMING_ID, 12)]) == 1

    assert [s for s in recorder.statements if s.startswith("UPDATE")] == []
    assert len([s for s in recorder.statements if s.startswith("SELECT id,")]) == 1


def test_row_older_than_the_window_is_not_reached(test_db, monkeypatch) -> None:
    _recording(monkeypatch, test_db)
    _insert_dispatch(
        test_db, event_id="dispatch-stale", created_at="2020-01-01T00:00:00Z"
    )

    assert hook_client_wall.record_client_wall_reports([(TIMING_ID, 55)]) == 1

    row = test_db.execute(
        "SELECT envelope FROM events WHERE event_id=%s", ("dispatch-stale",)
    ).fetchone()
    assert "client_wall_ms" not in json.loads(row[0])["context"]


def test_every_statement_runs_under_a_per_statement_timeout(
    test_db, monkeypatch
) -> None:
    recorder = _recording(monkeypatch, test_db)

    hook_client_wall.record_client_wall_reports([(TIMING_ID, 5)])

    assert recorder.statements[0] == (
        f"SET statement_timeout = {HOOK_OBSERVATION_STATEMENT_TIMEOUT_MS}"
    )
