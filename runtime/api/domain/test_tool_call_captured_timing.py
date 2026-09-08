"""Tool-call duration is measured between captured hook endpoints.

Covers both the interval itself and the named statuses that stand in when
an endpoint is missing or the pair is impossible, across the paths that
observe a completion: parsed in the hook (sync) and parsed at ingest after
bounded batch delivery (deferred).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import observe_parsing
from yoke_core.domain import observe_timing
from yoke_core.domain.observe_event_emission import build_envelope, insert_event


_POST_TOOL_PAYLOAD = {
    "tool_name": "Bash",
    "tool_input": {"command": "true"},
    "tool_response": {"content": "Exit code 0"},
}


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _open_tool_call(
    conn, *, session_id: str, tool_use_id: str, started_at: datetime
) -> None:
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at) "
        "VALUES (%s, %s, %s, %s)",
        (session_id, tool_use_id, "Bash", _stamp(started_at)),
    )
    conn.commit()


def _parse_completion(
    *, session_id: str, tool_use_id: str, completed_at
) -> observe_parsing.EventRecord:
    record = observe_parsing.parse_hook_event(
        dict(_POST_TOOL_PAYLOAD),
        session_id=session_id,
        hook_event="PostToolUse",
        tool_use_id=tool_use_id,
        db_path=None,
        completed_at=completed_at,
    )
    assert record is not None
    return record


def test_post_tool_duration_uses_connected_authority_without_db_token() -> None:
    with test_database() as conn:
        completed_at = datetime.now(timezone.utc)
        _open_tool_call(
            conn,
            session_id="duration-session",
            tool_use_id="tool-duration",
            started_at=completed_at - timedelta(milliseconds=80),
        )

        record = _parse_completion(
            session_id="duration-session",
            tool_use_id="tool-duration",
            completed_at=completed_at,
        )

        assert record.duration_ms == 80
        assert record.timing_status == observe_timing.TIMING_MEASURED
        insert_event(conn, build_envelope(record))
        row = conn.execute(
            "SELECT duration_ms, envelope FROM events "
            "WHERE event_name = 'HarnessToolCallCompleted' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == record.duration_ms
        envelope = json.loads(row[1])
        assert envelope["duration_ms"] == record.duration_ms
        assert (
            envelope["context"]["detail"]["timing_status"]
            == observe_timing.TIMING_MEASURED
        )


def test_duration_ignores_how_late_the_completion_is_measured() -> None:
    """A two-second call stays two seconds however late it is parsed."""
    with test_database() as conn:
        started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        _open_tool_call(
            conn,
            session_id="deferred-session",
            tool_use_id="deferred-call",
            started_at=started_at,
        )

        record = _parse_completion(
            session_id="deferred-session",
            tool_use_id="deferred-call",
            completed_at=started_at + timedelta(seconds=2),
        )

        assert record.duration_ms == 2000
        assert record.timing_status == observe_timing.TIMING_MEASURED


def test_duration_reads_only_the_calling_session_row() -> None:
    """A tool-use id is unique only within its session."""
    with test_database() as conn:
        completed_at = datetime.now(timezone.utc)
        _open_tool_call(
            conn,
            session_id="other-session",
            tool_use_id="shared-tool-use-id",
            started_at=completed_at - timedelta(seconds=30),
        )
        _open_tool_call(
            conn,
            session_id="owning-session",
            tool_use_id="shared-tool-use-id",
            started_at=completed_at - timedelta(milliseconds=250),
        )

        record = _parse_completion(
            session_id="owning-session",
            tool_use_id="shared-tool-use-id",
            completed_at=completed_at,
        )

        assert record.duration_ms == 250


def test_replayed_completion_measures_the_same_duration() -> None:
    """Replay is deterministic: both endpoints are captured, neither is now."""
    with test_database() as conn:
        completed_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        _open_tool_call(
            conn,
            session_id="replay-session",
            tool_use_id="replay-call",
            started_at=completed_at - timedelta(milliseconds=400),
        )

        first = _parse_completion(
            session_id="replay-session",
            tool_use_id="replay-call",
            completed_at=completed_at,
        )
        second = _parse_completion(
            session_id="replay-session",
            tool_use_id="replay-call",
            completed_at=completed_at,
        )

        assert first.duration_ms == second.duration_ms == 400


def test_unmeasurable_endpoints_are_named_rather_than_dropped() -> None:
    with test_database() as conn:
        completed_at = datetime.now(timezone.utc)
        _open_tool_call(
            conn,
            session_id="unknown-timing-session",
            tool_use_id="known-call",
            started_at=completed_at,
        )

        no_end = _parse_completion(
            session_id="unknown-timing-session",
            tool_use_id="known-call",
            completed_at=None,
        )
        no_start = _parse_completion(
            session_id="unknown-timing-session",
            tool_use_id="never-opened-call",
            completed_at=completed_at,
        )
        no_identity = _parse_completion(
            session_id="unknown-timing-session",
            tool_use_id="",
            completed_at=completed_at,
        )
        backwards = _parse_completion(
            session_id="unknown-timing-session",
            tool_use_id="known-call",
            completed_at=completed_at - timedelta(seconds=1),
        )

        for record, expected in (
            (no_end, observe_timing.TIMING_UNKNOWN_NO_CAPTURED_END),
            (no_start, observe_timing.TIMING_UNKNOWN_NO_RECORDED_START),
            (no_identity, observe_timing.TIMING_UNKNOWN_NO_CALL_IDENTITY),
            (backwards, observe_timing.TIMING_INVALID_NEGATIVE_ELAPSED),
        ):
            assert record.duration_ms is None
            assert record.timing_status == expected
            detail = build_envelope(record)["context"]["detail"]
            assert detail["timing_status"] == expected


def test_implausible_endpoint_pair_is_rejected_but_long_calls_are_kept() -> None:
    start = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    long_call = observe_timing.measure_elapsed(
        start, start + timedelta(hours=6)
    )
    mismatched = observe_timing.measure_elapsed(
        start, start + timedelta(days=3)
    )

    assert long_call.milliseconds == 6 * 60 * 60 * 1000
    assert long_call.status == observe_timing.TIMING_MEASURED
    assert mismatched.milliseconds is None
    assert mismatched.status == observe_timing.TIMING_INVALID_IMPLAUSIBLE_ELAPSED


def test_unparseable_endpoint_is_named_as_a_format_failure() -> None:
    measurement = observe_timing.measure_elapsed(
        "not-a-timestamp", datetime.now(timezone.utc)
    )

    assert measurement.milliseconds is None
    assert measurement.status == observe_timing.TIMING_INVALID_ENDPOINT_FORMAT
