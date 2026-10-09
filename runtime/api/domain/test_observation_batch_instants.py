"""Native batch heartbeat facts and explicit SQLite audit wire clocks."""

import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_chain_checkpoint_instants import _session
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import migration_harness_core as migration
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.observe_timing import ElapsedMeasurement
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.hooks import observation_batch as batch

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


def test_batch_clock_ingress_returns_native_qualified_instant():
    assert batch._observed_at(MOMENT) == MOMENT
    assert batch._observed_at("2026-10-09T15:56:12.345678+05:45") == MOMENT


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-10-09T10:11:12",
        "2026-02-30T10:11:12Z",
        0,
        MOMENT.replace(tzinfo=None),
    ],
)
def test_batch_invalid_clock_refuses_without_returning_a_guess(value):
    with pytest.raises(
        batch.ObservationBatchError, match="timestamp is (missing|invalid)"
    ):
        batch._observed_at(value)


@pytest.mark.parametrize("zone", ZONES)
def test_native_heartbeat_comparison_retains_microseconds_and_never_moves_back(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    session = _session(test_db)
    previous = MOMENT - timedelta(microseconds=1)
    test_db.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (previous, session),
    )
    test_db.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,last_heartbeat,reason) VALUES (%s,'item',%s,%s,%s,'Clock observation')",
        (session, make_item_target(1).scope_json(), previous, previous),
    )
    for clock in [MOMENT, previous]:
        batch._stamp_heartbeat(test_db, session, clock)
        assert (
            test_db.execute(
                "SELECT last_heartbeat FROM harness_sessions WHERE session_id=%s",
                (session,),
            ).fetchone()[0]
            == MOMENT
        )
        assert (
            test_db.execute(
                "SELECT last_heartbeat FROM work_claims WHERE session_id=%s", (session,)
            ).fetchone()[0]
            == MOMENT
        )


def test_batch_event_envelope_formats_only_owned_clock(monkeypatch):
    seen = []
    monkeypatch.setattr(
        batch,
        "parse_pre_event",
        lambda *_args, **_kwargs: {
            "context": {"detail": {"evidence": "2026-10-09 10:11:12+00:00"}}
        },
    )
    monkeypatch.setattr(
        batch, "insert_event", lambda _conn, envelope: seen.append(envelope)
    )
    batch._tool_event(
        object(),
        event_name="PreToolUse",
        payload={},
        context=SimpleNamespace(cwd="/tmp"),
        observed_at=MOMENT,
        event_id="clock-event",
        ingest_lag=ElapsedMeasurement(1, "measured"),
    )
    assert seen[0]["event_time"] == format_instant(MOMENT)
    assert seen[0]["context"]["detail"]["evidence"] == "2026-10-09 10:11:12+00:00"


def test_sqlite_failure_audit_preserves_native_start_microseconds(
    tmp_path, monkeypatch
):
    path = tmp_path / "migration-validation.sqlite3"
    conn = sqlite3.connect(path)
    ensure_migration_audit_table(conn)
    conn.close()
    later = MOMENT + timedelta(seconds=1, microseconds=1)
    monkeypatch.setattr(migration, "utc_now", lambda: later)
    monkeypatch.setattr(migration, "iso8601_now", lambda: format_instant(later))
    monkeypatch.setattr(migration, "_emit_event", lambda *_args, **_kwargs: None)
    operation = migration.GovernedMigration(
        name="Clock proof", tables=[], expected_deltas={}, db_path=str(path)
    )
    operation._start_time = MOMENT
    operation._rollback("Expected fixture refusal")
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT started_at,completed_at FROM migration_audit"
        ).fetchone()
        assert row == (format_instant(MOMENT), format_instant(later))
    finally:
        conn.close()
