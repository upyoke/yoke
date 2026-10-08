"""Launch batches drain without waiting behind serial control work."""

from __future__ import annotations

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import (
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


def test_one_poll_leases_the_assigned_burst_in_order() -> None:
    conn = _connection()
    queued = _queue(conn, 4)
    outcome = _claim(conn)
    assert [job.job_id for job in outcome.jobs] == sorted(queued)
    assert all(job.job_kind == "launch" for job in outcome.jobs)
    assert all(_hold_reason(conn, job.job_id) is None for job in outcome.jobs)


def test_new_launches_do_not_wait_for_an_outstanding_native_report() -> None:
    conn = _connection()
    _queue(conn, 1)
    (first,) = _claim(conn).jobs
    assigned_launch(conn, key="later", machine_id=MACHINE_ID)
    (second,) = _claim(conn, now="2026-08-22T12:00:01Z").jobs
    assert second.job_id != first.job_id
    batches = conn.execute(
        "SELECT DISTINCT batch_id FROM session_launch_attempts"
    ).fetchall()
    assert len(batches) == 1
    _report(conn, first, now="2026-08-22T12:00:02Z")
    assert conn.execute(
        "SELECT lease_id FROM session_relays WHERE relay_id=?", (RELAY_ID,)
    ).fetchone()[0]
    _report(conn, second, now="2026-08-22T12:00:03Z")
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?", (RELAY_ID,)
        ).fetchone()[0]
        is None
    )


def test_a_crash_after_lease_settles_every_launch_in_the_batch() -> None:
    conn = _connection()
    queued = _queue(conn, 2)
    assert len(_claim(conn).jobs) == 2
    assert settle_expired_relay_leases(conn, now="2026-08-22T12:30:00Z") == 2
    outcomes = dict(
        conn.execute(
            "SELECT launch_id,result_code FROM session_launch_attempts"
        ).fetchall()
    )
    assert outcomes == {key: "relay_lease_expired" for key in queued}


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


def test_an_eligible_wake_does_not_starve_assigned_launches() -> None:
    conn = _connection()
    _queue(conn, 3)
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")
    outcome = _claim(conn)
    assert [job.job_kind for job in outcome.jobs] == [
        "wake",
        "launch",
        "launch",
        "launch",
    ]
    assert outcome.jobs[0].target_session_id == "target-1"


def test_an_outstanding_wake_does_not_block_later_launches() -> None:
    conn = _connection()
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")
    assert _claim(conn).jobs[0].job_kind == "wake"
    _queue(conn, 2)
    assert [job.job_kind for job in _claim(conn, now="2026-08-22T12:00:01Z").jobs] == [
        "launch",
        "launch",
    ]


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
