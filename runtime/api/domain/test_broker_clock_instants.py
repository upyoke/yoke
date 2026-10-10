"""Peer wake SQL clocks, snapshot matching and expiry retain native precision."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.timestamps import InvalidInstant
from yoke_core.domain import session_broker_wake as broker
from yoke_core.domain import session_broker_wake_adoption as adoption
from yoke_core.domain import session_broker_wake_settlement as settlement
from yoke_core.domain.session_broker_wake_recruit import machine_has_fresh_relay
from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_message_types import ResolvedRecipient, row_dict
from yoke_core.domain.session_relay_storage import heartbeat_relay
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    WAKE_LEASE_SECONDS,
    WakeMode,
)
from runtime.api.domain.coordination_claim_test_support import seed_session

MOMENT = datetime(
    2026, 10, 9, 16, 11, 12, 345678, timezone(timedelta(hours=5, minutes=45))
)
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
BODY = "opaque instruction captured at 2026-10-09 10:26:12+00:00"
SNAPSHOT_CLOCKS = (
    "last_wake_at",
    "turn_posture_at",
    "last_heartbeat",
    "last_tool_call_at",
    "ended_at",
    "wake_after",
)


def _snapshot(conn, message_id):
    row = conn.execute(
        "SELECT r.*,hs.last_heartbeat,hs.last_tool_call_at,hs.turn_posture,"
        "hs.turn_posture_at,hs.ended_at FROM session_message_recipients r "
        "JOIN harness_sessions hs ON hs.session_id=r.session_id WHERE r.message_id=%s",
        (message_id,),
    ).fetchone()
    candidate = row_dict(row)
    candidate.update(
        project_id=1,
        wake_mode=WakeMode.WAITING.value,
        liveness="stale",
        parked=True,
        session_workspace="/tmp/target-clock",
    )
    for key in SNAPSHOT_CLOCKS:
        value = candidate.get(key)
        if value is not None:
            candidate[key] = value.astimezone(timezone(timedelta(hours=9))).isoformat()
    return candidate


def _prepare(conn):
    seed_session(conn, "broker-clock")
    seed_session(conn, "target-clock")
    machine_id = str(uuid4())
    version = capability_for_surface("codex-cli").minimum_version
    old = MOMENT - timedelta(minutes=11)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s,executor_surface='codex-cli',"
        "executor_version=%s,turn_posture='waiting',turn_posture_at=%s,"
        "last_heartbeat=%s,last_tool_call_at=%s,offered_at=%s,ended_at=NULL "
        "WHERE session_id IN ('broker-clock','target-clock')",
        (machine_id, version, old, old, old, old),
    )
    project = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]
    recipient = ResolvedRecipient(
        session_id="target-clock",
        project_id=1,
        project=project,
        executor="codex",
        executor_surface="codex-cli",
        executor_version=version,
        machine_id=machine_id,
        liveness="stale",
        messageability={"messageable": True},
    )
    message, inserted = insert_message(
        conn,
        sender_actor_id=2,
        sender_session_id="broker-clock",
        sender_surface="cli",
        body=BODY,
        selector_snapshot={},
        idempotency_key=None,
        created_at=old,
        expires_at=MOMENT + timedelta(hours=1),
        recipients=[recipient],
        actor_recipients=[],
        wake_after_by_project={1: old},
    )
    assert inserted
    message_id = message["message_id"]
    original = tuple(
        conn.execute(
            "SELECT body,body_sha256,selector_snapshot FROM session_messages WHERE message_id=%s",
            (message_id,),
        ).fetchone()
    )
    candidate = _snapshot(conn, message_id)
    conn.commit()
    heartbeat = RelayHeartbeat(
        "machine:" + machine_id,
        2,
        machine_id,
        "clock-test",
        "0.1.1",
        {"codex-cli": version},
        (1,),
    )
    return candidate, heartbeat, original


def _reserve(conn, candidate, now=MOMENT):
    return broker._reserve_candidate(
        conn,
        broker_session_id="broker-clock",
        candidate=candidate,
        now=now,
    )


def _assert_message_unchanged(conn, message_id, original):
    assert (
        tuple(
            conn.execute(
                "SELECT body,body_sha256,selector_snapshot FROM session_messages WHERE message_id=%s",
                (message_id,),
            ).fetchone()
        )
        == original
    )


@pytest.mark.parametrize("zone", ZONES)
def test_broker_reservation_and_close_preserve_native_microseconds_and_message(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    candidate, _, original = _prepare(test_db)
    started = MOMENT + timedelta(microseconds=1)
    lease = _reserve(test_db, candidate, started)
    assert lease is not None
    row = test_db.execute(
        "SELECT started_at,completed_at FROM session_message_attempts WHERE attempt_id=%s",
        (lease.attempt_id,),
    ).fetchone()
    assert isinstance(row[0], datetime) and tuple(row) == (started, None)
    assert (
        test_db.execute(
            "SELECT last_wake_at,wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == started
    )
    completed = started + timedelta(microseconds=1)
    result = settlement.complete_broker_hook_lease(
        test_db,
        lease_id=lease.lease_id,
        delivered=False,
        result="missing",
        now=completed,
    )
    assert result["result_code"] == "broker_render_missing"
    assert tuple(
        test_db.execute(
            "SELECT started_at,completed_at FROM session_message_attempts WHERE attempt_id=%s",
            (lease.attempt_id,),
        ).fetchone()
    ) == (started, completed)
    _assert_message_unchanged(test_db, lease.message_id, original)


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,closed", [(-1, 0), (0, 1), (1, 1)])
def test_broker_hook_lease_expires_inclusively_at_exact_microsecond(
    test_db, zone, delta, closed
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    candidate, _, original = _prepare(test_db)
    lease = _reserve(test_db, candidate)
    assert lease is not None
    current = MOMENT + timedelta(
        seconds=broker.BROKER_HOOK_LEASE_SECONDS, microseconds=delta
    )
    assert settlement.settle_broker_wake_losses(test_db, now=current) == closed
    row = test_db.execute(
        "SELECT completed_at,result_code FROM session_message_attempts WHERE attempt_id=%s",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(row) == (
        (current, "broker_hook_lease_expired")
        if closed
        else (None, "broker_hook_leased")
    )
    _assert_message_unchanged(test_db, lease.message_id, original)


@pytest.mark.parametrize("zone", ZONES)
def test_broker_adoption_accepts_equal_offset_snapshot_and_native_batch_clock(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    candidate, heartbeat, original = _prepare(test_db)
    lease = _reserve(test_db, candidate)
    assert lease is not None
    current = MOMENT + timedelta(microseconds=1)
    settlement.complete_broker_hook_lease(
        test_db,
        lease_id=lease.lease_id,
        delivered=True,
        result="rendered",
        now=current,
    )
    heartbeat_relay(
        test_db, heartbeat, state="active", next_poll_seconds=1, now=current
    )
    candidate = _snapshot(test_db, lease.message_id)
    test_db.commit()
    job = adoption._adopt_attempt(
        test_db,
        attempt_id=lease.attempt_id,
        candidate=candidate,
        heartbeat=heartbeat,
        now=current,
        qualification=None,
        execution=("codex-cli", heartbeat.surface_versions["codex-cli"]),
    )
    assert job is not None and job.message_id == lease.message_id
    row = test_db.execute(
        "SELECT last_seen_at,lease_expires_at FROM session_relays"
    ).fetchone()
    assert isinstance(row[0], datetime)
    assert tuple(row) == (current, current + timedelta(seconds=WAKE_LEASE_SECONDS))
    assert tuple(
        test_db.execute(
            "SELECT wake_attempt_count,last_wake_at FROM session_message_recipients"
        ).fetchone()
    ) == (1, MOMENT)
    _assert_message_unchanged(test_db, lease.message_id, original)


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,fresh", [(-1, True), (0, False), (1, False)])
def test_relay_freshness_is_strict_at_exact_native_microsecond(
    test_db, zone, delta, fresh
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _, heartbeat, _ = _prepare(test_db)
    edge = heartbeat_relay(
        test_db, heartbeat, state="active", next_poll_seconds=1, now=MOMENT
    )
    assert isinstance(edge, datetime) and edge == MOMENT + timedelta(seconds=2)
    assert (
        machine_has_fresh_relay(
            test_db, heartbeat.machine_id, edge + timedelta(microseconds=delta)
        )
        is fresh
    )


def test_changed_clock_snapshot_refuses_without_charging_receipt(test_db):
    candidate, _, original = _prepare(test_db)
    candidate["turn_posture_at"] = MOMENT - timedelta(minutes=11, microseconds=1)
    assert _reserve(test_db, candidate) is None
    assert tuple(
        test_db.execute(
            "SELECT wake_attempt_count,last_wake_at FROM session_message_recipients"
        ).fetchone()
    ) == (0, None)
    assert (
        test_db.execute("SELECT count(*) FROM session_message_attempts").fetchone()[0]
        == 0
    )
    _assert_message_unchanged(test_db, candidate["message_id"], original)


@pytest.mark.parametrize("value", ["", "2026-10-09", MOMENT.replace(tzinfo=None)])
def test_malformed_clock_snapshot_refuses_without_charging_receipt(test_db, value):
    candidate, _, _ = _prepare(test_db)
    candidate["turn_posture_at"] = value
    with pytest.raises(InvalidInstant):
        _reserve(test_db, candidate)
    assert (
        test_db.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute("SELECT count(*) FROM session_message_attempts").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("value", ["", "2026-10-09", MOMENT.replace(tzinfo=None)])
def test_malformed_broker_current_clock_refuses_before_sql(value):
    with pytest.raises(InvalidInstant):
        broker._reserve_candidate(
            object(), broker_session_id="broker-clock", candidate={}, now=value
        )
    with pytest.raises(InvalidInstant):
        settlement.close_broker_attempt(
            object(), attempt_id="attempt", result_code="closed", now=value
        )
    with pytest.raises(InvalidInstant):
        settlement.settle_broker_wake_losses(object(), now=value)
    with pytest.raises(InvalidInstant):
        settlement.complete_broker_hook_lease(
            object(), lease_id="lease", delivered=False, result="missing", now=value
        )
    with pytest.raises(InvalidInstant):
        machine_has_fresh_relay(object(), "machine", value)
    with pytest.raises(InvalidInstant):
        adoption.claim_broker_wake_job(
            object(),
            None,
            now=value,
            broker_lease_id="lease",
            broker_session_id="broker-clock",
        )
