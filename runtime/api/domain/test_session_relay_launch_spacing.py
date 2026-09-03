"""One launch per poll, native creates on a machine spaced apart, wakes serial."""

from __future__ import annotations

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_launch_lease import spawn_hold_until
from yoke_core.domain.session_relay_types import (
    NATIVE_SPAWN_SPACING_SECONDS,
    RelayHeartbeat,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _connection():
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    return conn


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _queue(conn, count: int) -> list[str]:
    return [
        assigned_launch(conn, key=f"burst-{index}", machine_id=MACHINE_ID).launch_id
        for index in range(count)
    ]


def _claim(conn, now: str = NOW):
    return claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: now,
    )


def _report(conn, job, *, now: str, native: str | None = "native-session"):
    return report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="native_created" if native else "not_created",
        native_session_id=native,
        now=now,
    )


def _hold_reason(conn, launch_id: str) -> str | None:
    return conn.execute(
        "SELECT spawn_hold_reason FROM session_launches WHERE launch_id=?",
        (launch_id,),
    ).fetchone()[0]


def test_one_poll_leases_exactly_one_launch_from_a_burst() -> None:
    conn = _connection()
    queued = _queue(conn, 4)

    outcome = _claim(conn)

    # Same-instant launches tie-break on launch id, so oldest-first is that order.
    assert [job.job_id for job in outcome.jobs] == sorted(queued)[:1]
    assert outcome.jobs[0].job_kind == "launch"
    assert _hold_reason(conn, outcome.jobs[0].job_id) is None


def test_the_next_native_create_waits_out_the_spacing_window_and_says_why() -> None:
    conn = _connection()
    first_id, second_id = sorted(_queue(conn, 2))
    (first,) = _claim(conn).jobs
    assert first.job_id == first_id
    _report(conn, first, now="2026-08-22T12:00:05Z")

    # Reported and drained, but the machine started a create five seconds ago.
    held = _claim(conn, now="2026-08-22T12:00:10Z")
    assert held.jobs == ()
    reason = _hold_reason(conn, second_id)
    assert reason is not None
    assert f"less than {NATIVE_SPAWN_SPACING_SECONDS}s ago" in reason
    assert "next create not before 2026-08-22T12:00:30Z" in reason
    assert spawn_hold_until(
        conn, machine_id=MACHINE_ID, now="2026-08-22T12:00:10Z"
    ) == ("2026-08-22T12:00:30Z")

    (second,) = _claim(conn, now="2026-08-22T12:00:30Z").jobs
    assert second.job_id == second_id
    assert _hold_reason(conn, second_id) is None
    assert spawn_hold_until(
        conn, machine_id=MACHINE_ID, now="2026-08-22T12:00:30Z"
    ) == ("2026-08-22T12:01:00Z")


def test_a_relay_mid_create_is_handed_nothing_until_it_reports() -> None:
    conn = _connection()
    _queue(conn, 2)
    (first,) = _claim(conn).jobs

    assert _claim(conn, now="2026-08-22T12:00:45Z").jobs == ()
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is not None
    )

    _report(conn, first, now="2026-08-22T12:00:50Z")

    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is None
    )
    assert len(_claim(conn, now="2026-08-22T12:00:55Z").jobs) == 1


def test_a_crash_after_lease_strands_only_the_leased_launch() -> None:
    conn = _connection()
    _queue(conn, 2)
    (first,) = _claim(conn).jobs

    settled = settle_expired_relay_leases(conn, now="2026-08-22T12:30:00Z")

    assert settled == 1
    outcomes = dict(
        conn.execute(
            "SELECT launch_id,result_code FROM session_launch_attempts"
        ).fetchall()
    )
    assert outcomes == {first.job_id: "relay_lease_expired"}
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is None
    )


def test_the_claim_response_carries_no_stagger_field() -> None:
    conn = _connection()
    _queue(conn, 1)

    outcome = _claim(conn)

    assert "launch_stagger_seconds" not in outcome.to_dict()


def _add_waiting_recipient(conn, *, message_id: str, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,"
        "model,offered_at,last_tool_call_at,ended_at,turn_posture) "
        "VALUES (?,10,'codex-cli','0.148.0a15',?,'gpt-5',?,NULL,?,'waiting')",
        (session_id, MACHINE_ID, "2026-08-22T10:00:00Z", "2026-08-22T10:30:00Z"),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at) VALUES (?,1,?,'sha256:body','{}',?,?)",
        (
            message_id,
            "Never send this body through the native wake adapter.",
            "2026-08-22T11:00:00Z",
            "2026-08-23T12:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "executor_surface,executor_version,machine_id,state,created_at,wake_after) "
        "VALUES (?,?,10,'{}','{}','codex-cli','0.148.0a15',?,"
        "'pending','2026-08-22T11:00:00Z','2026-08-22T11:10:00Z')",
        (message_id, session_id, MACHINE_ID),
    )
    conn.commit()


def test_wakes_stay_one_per_cycle_even_when_several_are_eligible() -> None:
    conn = _connection()
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")
    _add_waiting_recipient(conn, message_id="message-2", session_id="target-2")

    outcome = _claim(conn)

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].job_kind == "wake"
    # The single wake holds the relay until it is reported.
    assert _claim(conn, now="2026-08-22T12:00:01Z").jobs == ()


def test_a_launch_is_claimed_before_an_eligible_wake() -> None:
    conn = _connection()
    queued = _queue(conn, 1)
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")

    outcome = _claim(conn)

    assert [job.job_id for job in outcome.jobs] == queued
    assert outcome.jobs[0].job_kind == "launch"
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


def test_a_relay_stays_eligible_for_the_whole_create_it_is_executing() -> None:
    conn = _connection()
    _queue(conn, 1)

    outcome = _claim(conn)

    horizon = conn.execute(
        "SELECT lease_expires_at FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()[0]
    assert len(outcome.jobs) == 1
    # A native create on a loaded box outlasts a poll interval, so the
    # connection edge has to follow the lease rather than the cadence.
    assert outcome.connected_until >= horizon
    assert eligible_relay_ids(conn, now=horizon)


def eligible_relay_ids(conn, *, now: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT relay_id FROM session_relays "
            "WHERE state IN ('active','idle') AND connected_until >= ?",
            (now,),
        ).fetchall()
    ]
