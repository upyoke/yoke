"""Batched launch leasing, partial reporting, and serial wake claims."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_storage import relay_holds_batch
from yoke_core.domain.session_relay_types import RelayHeartbeat, SessionRelayError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _connection(batch: int | None = None, stagger: int | None = None):
    fleet: dict[str, int] = {}
    if batch is not None:
        fleet["relay_launch_batch"] = batch
    if stagger is not None:
        fleet["relay_launch_stagger_seconds"] = stagger
    conn = relay_connection({"fleet": fleet} if fleet else None)
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


def test_one_poll_drains_a_launch_burst_up_to_the_configured_cap() -> None:
    conn = _connection(batch=5)
    queued = _queue(conn, 7)

    outcome = _claim(conn)

    # Same-instant launches tie-break on launch id, so oldest-first is that order.
    assert [job.job_id for job in outcome.jobs] == sorted(queued)[:5]
    assert all(job.job_kind == "launch" for job in outcome.jobs)
    assert outcome.to_dict()["jobs"][0]["job_id"] == sorted(queued)[0]


def test_each_batched_launch_carries_its_own_lease_and_attestation() -> None:
    conn = _connection(batch=3)
    _queue(conn, 3)

    outcome = _claim(conn)

    leases = [job.lease_id for job in outcome.jobs]
    assert len(set(leases)) == 3
    assert len(set(job.launch_attestation for job in outcome.jobs)) == 3
    # The batch marker is relay-level and is never one of the job leases.
    marker = conn.execute(
        "SELECT lease_id FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()[0]
    assert marker not in leases
    for job in outcome.jobs:
        stored = conn.execute(
            "SELECT lease_id FROM session_launch_attempts WHERE launch_id=?",
            (job.job_id,),
        ).fetchone()[0]
        assert stored == job.lease_id


def test_a_launch_lease_cannot_settle_another_launch_in_the_same_batch() -> None:
    conn = _connection(batch=2)
    _queue(conn, 2)
    first, second = _claim(conn).jobs

    with pytest.raises(SessionRelayError) as mismatched:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=RELAY_ID,
            job_kind="launch",
            job_id=second.job_id,
            lease_id=first.lease_id,
            result_code="native_created",
            native_session_id="native-session",
            now="2026-08-22T12:00:10Z",
        )

    assert mismatched.value.code == "attempt_missing"


def test_a_partly_reported_batch_holds_the_relay_until_every_job_settles() -> None:
    conn = _connection(batch=3)
    _queue(conn, 3)
    first, second, third = _claim(conn).jobs

    _report(conn, first, now="2026-08-22T12:00:05Z")
    _report(conn, second, now="2026-08-22T12:00:06Z", native=None)

    assert _claim(conn, now="2026-08-22T12:00:07Z").jobs == ()
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is not None
    )

    _report(conn, third, now="2026-08-22T12:00:08Z")

    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is None
    )


def test_a_crash_mid_batch_strands_only_the_jobs_never_reported() -> None:
    conn = _connection(batch=3)
    _queue(conn, 3)
    first, second, third = _claim(conn).jobs
    _report(conn, first, now="2026-08-22T12:00:05Z")

    settled = settle_expired_relay_leases(conn, now="2026-08-22T12:30:00Z")

    assert settled == 2
    outcomes = dict(
        conn.execute(
            "SELECT launch_id,result_code FROM session_launch_attempts"
        ).fetchall()
    )
    assert outcomes[first.job_id] == "native_created"
    assert outcomes[second.job_id] == "outcome_unknown"
    assert outcomes[third.job_id] == "outcome_unknown"
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
        is None
    )


def test_the_claim_response_carries_the_organization_stagger() -> None:
    conn = _connection(batch=2, stagger=3)
    _queue(conn, 2)

    outcome = _claim(conn)

    assert outcome.launch_stagger_seconds == 3
    assert outcome.to_dict()["launch_stagger_seconds"] == 3


def test_a_queued_launch_burst_never_exceeds_a_cap_of_one() -> None:
    conn = _connection(batch=1)
    queued = _queue(conn, 4)

    outcome = _claim(conn)

    assert [job.job_id for job in outcome.jobs] == sorted(queued)[:1]


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
    conn = _connection(batch=5)
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")
    _add_waiting_recipient(conn, message_id="message-2", session_id="target-2")

    outcome = _claim(conn)

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].job_kind == "wake"
    # The single wake holds the relay until it is reported.
    assert _claim(conn, now="2026-08-22T12:00:01Z").jobs == ()


def test_a_launch_burst_is_claimed_before_an_eligible_wake() -> None:
    conn = _connection(batch=2)
    queued = _queue(conn, 2)
    _add_waiting_recipient(conn, message_id="message-1", session_id="target-1")

    outcome = _claim(conn)

    assert sorted(job.job_id for job in outcome.jobs) == sorted(queued)
    assert all(job.job_kind == "launch" for job in outcome.jobs)
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


def test_a_relay_that_moved_to_a_newer_batch_no_longer_holds_the_old_one() -> None:
    conn = _connection(batch=2)
    _queue(conn, 2)
    first, second = _claim(conn).jobs
    stale_batch = conn.execute(
        "SELECT lease_id FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()[0]
    conn.execute(
        "UPDATE session_relays SET lease_id='newer-batch',"
        "lease_expires_at='2026-08-22T12:10:00Z' WHERE relay_id=?",
        (RELAY_ID,),
    )
    conn.commit()

    # Both attempts still name the batch they were leased under, and the relay
    # no longer owns it, so neither is still held.
    batches = {
        row[0]
        for row in conn.execute(
            "SELECT batch_id FROM session_launch_attempts"
        ).fetchall()
    }
    assert batches == {stale_batch}
    assert not relay_holds_batch(
        conn, relay_id=RELAY_ID, batch_id=stale_batch, now="2026-08-22T12:06:00Z"
    )
    assert relay_holds_batch(
        conn, relay_id=RELAY_ID, batch_id="newer-batch", now="2026-08-22T12:06:00Z"
    )
    assert first.job_id != second.job_id


def test_a_relay_stays_eligible_for_the_whole_batch_it_is_executing() -> None:
    conn = _connection(batch=5)
    _queue(conn, 5)

    outcome = _claim(conn)

    horizon = conn.execute(
        "SELECT lease_expires_at FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()[0]
    assert len(outcome.jobs) == 5
    # Executing five native creates outlasts two poll intervals, so the
    # connection edge has to follow the batch rather than the cadence.
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
