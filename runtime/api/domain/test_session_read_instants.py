"""Native session read ordering, canonical cursors and effective catalog boundaries."""

import base64
from datetime import timedelta
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import model_reference_store as models
from yoke_core.domain.session_history_cursor import decode
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
    record_native_process_gone,
)
from yoke_core.domain.session_staleness import activity_liveness
from yoke_core.domain.sessions_history_read import read_ended_session_history
from yoke_core.domain.sessions_list_query import build_sessions_query
from yoke_core.domain.sessions_list_rows import _latest_activity


MOMENT = parse_instant("2026-11-01T05:29:59.123456+05:30")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_session_history_pages_exact_microseconds_and_native_roster_order(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    project = test_db.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()[
        0
    ]
    ids = sorted(str(uuid4()) for _ in range(3))
    for session_id, activity in zip(
        ids, (MOMENT, MOMENT, MOMENT + timedelta(microseconds=1))
    ):
        test_db.execute(
            "INSERT INTO harness_sessions (session_id,executor,provider,model,workspace,"
            "project_id,offered_at,last_heartbeat,last_tool_call_at,ended_at,tool_call_count) "
            "VALUES (%s,'codex','openai','gpt-6-sol','/tmp',%s,%s,%s,NULL,%s,1)",
            (session_id, project, MOMENT, activity, activity),
        )
    test_db.commit()
    first = read_ended_session_history(test_db, project_ids=[project], limit=2)
    second = read_ended_session_history(
        test_db, project_ids=[project], limit=2, cursor=first["next_cursor"]
    )
    assert [r["session_id"] for r in first["rows"]] == [ids[2], ids[1]]
    assert [r["session_id"] for r in second["rows"]] == [ids[0]]
    assert first["rows"][0]["activity_at"] == format_instant(
        MOMENT + timedelta(microseconds=1)
    )
    assert first["rows"][1]["ended_at"] == format_instant(MOMENT)
    assert first["rows"][1]["terminated_at"] is None
    assert decode(first["next_cursor"]) == (MOMENT, ids[1])
    assert second["next_cursor"] is None
    for windowed in (False, True):
        query = build_sessions_query("WHERE s.project_id=%s", windowed=windowed)
        params = (project, 5, 5) if windowed else (project, 5)
        rows = test_db.execute(query, params).fetchall()
        assert rows[0]["session_id"] == ids[2]


@pytest.mark.parametrize(
    "old",
    [
        '{"activity_at":"2026-11-01T00:00:00Z","session_id":"s"}',
        '{"v":1,"activity_at":"2026-11-01T00:00:00Z","session_id":"s"}',
        '{"v":1,"activity_at":"2026-11-01T05:30:00.000000+05:30","session_id":"s"}',
        '{"v":true,"activity_at":"2026-11-01T00:00:00.000000Z","session_id":"s"}',
    ],
)
def test_history_cursor_refuses_old_or_noncanonical_generations(old):
    cursor = base64.urlsafe_b64encode(old.encode()).decode()
    with pytest.raises(ValueError, match="clear it and reload"):
        decode(cursor)


def test_activity_order_uses_instants_and_refuses_naive_values():
    heartbeat = "1970-01-01T00:00:00.000000Z"
    tool = "1970-01-01T05:29:59.999999+05:30"
    assert _latest_activity(heartbeat, tool) == (heartbeat, parse_instant(heartbeat))
    assert (
        activity_liveness(
            {"last_heartbeat": heartbeat, "last_tool_call_at": tool},
            now=parse_instant(heartbeat),
        )
        == "active"
    )
    with pytest.raises(InvalidInstant):
        _latest_activity("1970-01-01T00:00:00", None)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_model_catalog_selects_native_exact_effective_boundary(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(models, "utc_now", lambda: MOMENT)
    original = models.latest_revision(test_db)
    effective = MOMENT + timedelta(microseconds=1)
    published = models.publish_catalog(
        test_db,
        [r.to_dict() for r in original["records"]],
        effective_at=effective.isoformat(),
        actor_id=1,
        source_note="Exact effective boundary",
        expected_base_revision_id=original["revision_id"],
    )
    assert published["effective_at"] == format_instant(effective)
    stored = test_db.execute(
        "SELECT effective_at,published_at,pg_typeof(effective_at)::text "
        "FROM model_reference_revisions WHERE revision_id=%s",
        (published["revision_id"],),
    ).fetchone()
    assert stored == (effective, MOMENT, "timestamp with time zone")
    schedule = models.revision_schedule(test_db)
    assert (
        models.revision_from_schedule(schedule, MOMENT)["revision_id"]
        == original["revision_id"]
    )
    assert (
        models.revision_from_schedule(schedule, effective)["revision_id"]
        == published["revision_id"]
    )
    assert (
        models.revision_at(test_db, effective.isoformat())["effective_at"] == effective
    )
    assert models.revisions_list(test_db)[0]["published_at"] == format_instant(MOMENT)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_native_process_reports_preserve_microsecond_death_order(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    session_id = str(uuid4())
    test_db.execute(
        "INSERT INTO harness_sessions (session_id,executor,provider,model,workspace,"
        "offered_at,last_heartbeat) VALUES (%s,'codex','openai','gpt-6-sol',"
        "'/tmp',%s,%s)",
        (session_id, MOMENT, MOMENT),
    )
    first = {"pids": [1], "process_start_times": {"1": "opaque-first"}}
    later = {"pids": [2], "process_start_times": {"2": "opaque-later"}}
    after = MOMENT + timedelta(microseconds=1)
    record_native_process_gone(test_db, session_id, first, observed_at=MOMENT)
    record_native_process_gone(test_db, session_id, later, observed_at=after)
    dropped = record_native_process_gone(test_db, session_id, first, observed_at=MOMENT)
    assert dropped["observed_at"] == format_instant(after)
    assert dropped["evidence"] == later
    row = dict(
        test_db.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,)
        ).fetchone()
    )
    assert row["native_process_gone_at"] == after
    assert current_native_process_observation(row)["observed_at"] == format_instant(
        after
    )
    assert current_native_process_observation({**row, "last_tool_call_at": after})
    assert (
        current_native_process_observation(
            {**row, "last_tool_call_at": after + timedelta(microseconds=1)}
        )
        is None
    )
    test_db.rollback()
