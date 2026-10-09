"""Wake cutoffs and recovery records retain native clocks at their SQL owners."""

from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import session_native_turn_end as turn_end
from yoke_core.domain import session_stale_alive_probe as probe
from yoke_core.domain import session_wake_deferral as deferral
from yoke_core.domain import session_wake_idempotency as idempotency
from yoke_core.domain import steering_message_drain as drain
from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_message_types import ResolvedRecipient, row_dict
from yoke_core.domain.sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES
from runtime.api.domain.coordination_claim_test_support import seed_session

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
OPAQUE = "foreign detail 2026-10-09 10:26:12+00:00"


def _seed(conn):
    seed_session(conn, "wake-clock")
    machine_id = str(uuid4())
    old = MOMENT - timedelta(hours=2)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s,executor_surface='codex-cli',"
        "turn_posture='running',turn_posture_at=%s,last_heartbeat=%s,last_tool_call_at=%s "
        "WHERE session_id='wake-clock'",
        (machine_id, old, old, old),
    )
    project = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]
    recipient = ResolvedRecipient(
        session_id="wake-clock",
        project_id=1,
        project=project,
        executor="codex",
        executor_surface="codex-cli",
        executor_version=None,
        machine_id=machine_id,
        liveness="stale",
        messageability={"messageable": True},
    )
    message, inserted = insert_message(
        conn,
        sender_actor_id=2,
        sender_session_id=None,
        sender_surface="cli",
        body=OPAQUE,
        selector_snapshot={},
        idempotency_key=probe.probe_key("wake-clock"),
        created_at=old,
        expires_at=MOMENT,
        recipients=[recipient],
        actor_recipients=[],
        wake_after_by_project={1: old},
    )
    assert inserted
    return message["message_id"], machine_id


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,open_count", [(-1, 1), (0, 0), (1, 0)])
def test_probe_receipt_and_native_turn_target_expiry_are_strict_at_microsecond(
    test_db,
    zone,
    delta,
    open_count,
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    message_id, machine_id = _seed(test_db)
    test_db.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,result_code,evidence) "
        "VALUES (%s,%s,'wake-clock','wake_relay',%s,%s,'skipped_operation','{}')",
        (str(uuid4()), message_id, MOMENT - timedelta(seconds=1), MOMENT),
    )
    now = MOMENT + timedelta(microseconds=delta)
    assert probe._has_live_probe(test_db, "wake-clock", now=now) is bool(open_count)
    rows = idempotency._open_receipts(test_db, session_id="wake-clock", now=now)
    assert len(rows) == open_count
    if rows:
        assert isinstance(rows[0]["created_at"], datetime)
    targets = turn_end.probe_targets(
        test_db,
        machine_id=machine_id,
        authorized_projects=(1,),
        now=now,
    )
    assert len(targets) == open_count


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,refunded", [(-1, True), (0, True), (1, False)])
def test_deferral_backoff_and_refund_comparison_preserve_native_microsecond(
    test_db,
    monkeypatch,
    zone,
    delta,
    refunded,
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    message_id, _ = _seed(test_db)
    monkeypatch.setattr(
        deferral,
        "project_policy",
        lambda *_: SimpleNamespace(wake_after_idle_seconds=60),
    )
    backoff = MOMENT + timedelta(seconds=60)
    original = backoff + timedelta(microseconds=delta)
    test_db.execute(
        "UPDATE session_message_recipients SET wake_attempt_count=1,wake_after=%s",
        (original,),
    )
    deferral.restore_deferred_wake_budget(
        test_db,
        message_id=message_id,
        session_id="wake-clock",
        now=MOMENT,
    )
    row = test_db.execute(
        "SELECT wake_attempt_count,wake_after FROM session_message_recipients"
    ).fetchone()
    assert isinstance(row[1], datetime)
    assert tuple(row) == (0 if refunded else 1, backoff if refunded else original)


@pytest.mark.parametrize("zone", ZONES)
def test_native_turn_report_keeps_native_posture_record_clock_and_explicit_json(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _, machine_id = _seed(test_db)
    observed = MOMENT - timedelta(microseconds=1)
    result = turn_end.apply_native_turn_ends(
        test_db,
        machine_id=machine_id,
        authorized_projects=(1,),
        now=MOMENT,
        reports=[
            {
                "session_id": "wake-clock",
                "observed_at": observed,
                "evidence": {"detail": OPAQUE},
            }
        ],
    )
    assert result == {"reclassified": ["wake-clock"], "skipped": []}
    row = test_db.execute(
        "SELECT turn_posture_at,native_turn_end_recorded_at,native_turn_end_observation "
        "FROM harness_sessions WHERE session_id='wake-clock'",
    ).fetchone()
    assert isinstance(row[0], datetime) and tuple(row[:2]) == (observed, MOMENT)
    body = json.loads(row[2])
    assert body["observed_at"] == format_instant(observed) and body["detail"] == OPAQUE


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,asked", [(-1, 1), (0, 0), (1, 0)])
def test_stale_probe_threshold_selects_latest_native_activity_with_strict_order(
    test_db,
    monkeypatch,
    zone,
    delta,
    asked,
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _seed(test_db)
    boundary = MOMENT - timedelta(minutes=DEFAULT_STALE_THRESHOLD_MINUTES, seconds=60)
    test_db.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s,last_tool_call_at=%s WHERE session_id='wake-clock'",
        (
            boundary - timedelta(microseconds=2),
            boundary + timedelta(microseconds=delta),
        ),
    )
    row = row_dict(
        test_db.execute(
            "SELECT * FROM harness_sessions WHERE session_id='wake-clock'"
        ).fetchone()
    )
    assert isinstance(row["last_heartbeat"], datetime)
    monkeypatch.setattr(
        probe, "_claim_holding_quiet_sessions", lambda *_args, **_kwargs: [row]
    )
    monkeypatch.setattr(
        probe,
        "project_policy",
        lambda *_: SimpleNamespace(stale_alive_probe_seconds=60),
    )
    sent = []

    def send(_conn, candidate):
        sent.append(candidate["session_id"])

    monkeypatch.setattr(probe, "_send_probe", send)
    result = probe.probe_stale_alive_sessions(
        test_db,
        machine_id=row["machine_id"],
        authorized_projects=(1,),
        now=MOMENT,
    )
    assert len(sent) == asked and len(result["probed"]) == asked


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("state", ["pending", "acknowledged"])
def test_steering_cancel_clock_is_native_and_acknowledged_recipient_is_retained(
    test_db, zone, state
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    message_id, _ = _seed(test_db)
    test_db.execute("UPDATE session_message_recipients SET state=%s", (state,))
    drain._cancel_session_recipient(
        test_db, message_id=message_id, session_id="wake-clock", now=MOMENT
    )
    assert tuple(
        test_db.execute(
            "SELECT state,cancelled_at FROM session_message_recipients"
        ).fetchone()
    ) == (("cancelled", MOMENT) if state == "pending" else ("acknowledged", None))
    row = {
        "sent_at": MOMENT,
        "sender_item_id": None,
        "state": "awaiting_seat",
        "body": OPAQUE,
    }
    digest = drain.render_digest(test_db, [row], descriptor="clock test")
    assert format_instant(MOMENT) in digest and OPAQUE in digest
    assert (
        test_db.execute(
            "SELECT body FROM session_messages WHERE message_id=%s", (message_id,)
        ).fetchone()[0]
        == OPAQUE
    )


@pytest.mark.parametrize("value", ["", "2026-10-09", MOMENT.replace(tzinfo=None)])
def test_invalid_wake_clock_refuses_before_sql_or_backoff_updates(value):
    with pytest.raises(InvalidInstant):
        probe._has_live_probe(object(), "wake-clock", now=value)
    with pytest.raises(InvalidInstant):
        probe.probe_stale_alive_sessions(
            object(), machine_id="machine", authorized_projects=(1,), now=value
        )
    with pytest.raises(InvalidInstant):
        idempotency._open_receipts(object(), session_id="wake-clock", now=value)
    with pytest.raises(InvalidInstant):
        turn_end.probe_targets(
            object(), machine_id="machine", authorized_projects=(1,), now=value
        )
    with pytest.raises(InvalidInstant):
        turn_end.apply_native_turn_ends(
            object(),
            machine_id="machine",
            authorized_projects=(1,),
            reports=[],
            now=value,
        )
    with pytest.raises(InvalidInstant):
        deferral.restore_deferred_wake_budget(
            object(), message_id="message", session_id="wake-clock", now=value
        )
    with pytest.raises(InvalidInstant):
        drain._cancel_session_recipient(
            object(), message_id="message", session_id="wake-clock", now=value
        )
