"""Reading one machine's own evidence from a seat that is somewhere else."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)
from yoke_contracts.session_control.evidence_fetch import (
    EVIDENCE_MAX_BYTES,
    evidence_pull_command,
    evidence_pull_suffix,
)
from yoke_core.domain.session_evidence_fetch import (
    evidence_fetch_result,
    read_evidence_fetch,
    request_evidence_fetch,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat, SessionRelayError


OWNING_MACHINE = "11111111-1111-4111-8111-111111111111"
OWNING_RELAY = f"machine:{OWNING_MACHINE}"
OTHER_MACHINE = "44444444-4444-4444-8444-444444444444"
TARGET_SESSION_ID = "22222222-2222-4222-8222-222222222222"
DIAGNOSTIC_REF = "nd-" + "ab" * 16
FETCH_ID = "55555555-5555-4555-8555-555555555555"


def _heartbeat(machine_id: str = OWNING_MACHINE) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=f"machine:{machine_id}",
        actor_id=1,
        machine_id=machine_id,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _connection():
    conn = relay_connection()
    add_relay(conn, relay_id=OWNING_RELAY, machine_id=OWNING_MACHINE)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,"
        "model,executor,execution_lane,last_heartbeat,offered_at) "
        "VALUES (?,?,?,?,?,?,'codex','direct',?,?)",
        (
            TARGET_SESSION_ID,
            10,
            "codex-cli",
            "0.148.0a15",
            OWNING_MACHINE,
            "gpt-5",
            NOW,
            NOW,
        ),
    )
    conn.commit()
    return conn


def _pending_fetch(conn, *, diagnostic_ref: str | None = None) -> None:
    conn.execute(
        "INSERT INTO session_evidence_fetches "
        "(fetch_id,target_session_id,project_id,machine_id,kind,diagnostic_ref,"
        "tail_lines,state,requested_at,requested_by_actor_id) "
        "VALUES (?,?,?,?,?,?,?, 'pending',?,?)",
        (
            FETCH_ID,
            TARGET_SESSION_ID,
            10,
            OWNING_MACHINE,
            "diagnostic" if diagnostic_ref else None,
            diagnostic_ref,
            200,
            NOW,
            1,
        ),
    )
    conn.commit()


def test_capture_round_trips_from_the_machine_that_owns_it() -> None:
    conn = _connection()
    _pending_fetch(conn, diagnostic_ref=DIAGNOSTIC_REF)

    claimed = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    )

    assert len(claimed.jobs) == 1
    job = claimed.jobs[0]
    assert job.job_kind == "evidence"
    assert job.job_id == FETCH_ID
    assert job.target_session_id == TARGET_SESSION_ID
    # The machine cannot key captures by session on its own, so the control
    # plane hands it the exact references that session's attempts reported.
    assert job.evidence_request["diagnostic_refs"] == [DIAGNOSTIC_REF]
    assert job.evidence_request["tail_lines"] == 200
    assert job.native_instruction == ""

    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=OWNING_RELAY,
        job_kind="evidence",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="read",
        document={
            "files": [
                {
                    "name": DIAGNOSTIC_REF,
                    "kind": "diagnostic",
                    "size_bytes": 91,
                    "modified_at": NOW,
                }
            ],
            "selected_file": DIAGNOSTIC_REF,
            "content": "native exited 1\npermission bypass unaccepted",
            "truncated": False,
        },
        now="2026-08-22T12:00:07Z",
    )

    assert result == {"fetch_id": FETCH_ID, "result_code": "read"}
    answer = evidence_fetch_result(read_evidence_fetch(conn, FETCH_ID))
    assert answer["state"] == "succeeded"
    assert answer["selected_file"] == DIAGNOSTIC_REF
    assert "permission bypass unaccepted" in answer["content"]
    assert answer["files"][0]["kind"] == "diagnostic"
    # A settled answer has nothing left to read back.
    assert answer["recovery"] is None


def test_only_the_owning_machine_may_lease_the_read() -> None:
    conn = _connection()
    _pending_fetch(conn)

    claimed = claim_relay_job(
        conn, _heartbeat(OTHER_MACHINE), wait_seconds=0, now_provider=lambda: NOW
    )

    assert claimed.jobs == ()
    assert (
        conn.execute("SELECT state FROM session_evidence_fetches").fetchone()[0]
        == "pending"
    )


def test_reported_content_is_capped_in_bytes() -> None:
    conn = _connection()
    _pending_fetch(conn)
    job = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    ).jobs[0]

    report_relay_job(
        conn,
        actor_id=1,
        relay_id=OWNING_RELAY,
        job_kind="evidence",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="read",
        document={"selected_file": "relay.stderr.log", "content": "x" * 500_000},
        now="2026-08-22T12:00:07Z",
    )

    row = read_evidence_fetch(conn, FETCH_ID)
    assert len(str(row["content"])) == EVIDENCE_MAX_BYTES
    assert int(row["content_bytes"]) == EVIDENCE_MAX_BYTES


def test_unknown_session_refuses_by_name() -> None:
    conn = _connection()

    with pytest.raises(Exception) as caught:
        request_evidence_fetch(
            conn,
            actor_id=1,
            caller_session_id=None,
            session_id="66666666-6666-4666-8666-666666666666",
            kind=None,
            file_name=None,
            evidence_id=None,
            tail_lines=200,
            now=NOW,
        )

    assert "66666666-6666-4666-8666-666666666666" in str(caught.value)
    assert conn.execute(
        "SELECT COUNT(*) FROM session_evidence_fetches"
    ).fetchone()[0] == 0


def test_a_report_from_another_relay_is_refused() -> None:
    conn = _connection()
    _pending_fetch(conn)
    job = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    ).jobs[0]

    with pytest.raises(SessionRelayError) as caught:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=OWNING_RELAY,
            job_kind="evidence",
            job_id=job.job_id,
            lease_id="00000000-0000-4000-8000-000000000000",
            result_code="read",
            document={"content": "not mine"},
            now="2026-08-22T12:00:07Z",
        )

    assert caught.value.code == "lease_mismatch"


def test_a_pending_answer_names_the_command_that_reads_it_back() -> None:
    conn = _connection()
    _pending_fetch(conn, diagnostic_ref=DIAGNOSTIC_REF)

    answer = evidence_fetch_result(read_evidence_fetch(conn, FETCH_ID))

    assert answer["state"] == "pending"
    assert answer["recovery"] == evidence_pull_command(
        TARGET_SESSION_ID, DIAGNOSTIC_REF
    )


def test_report_rows_share_one_pull_renderer() -> None:
    assert evidence_pull_suffix("") == ""
    assert evidence_pull_suffix(TARGET_SESSION_ID) == (
        f"; evidence `yoke session-control evidence get "
        f"--session {TARGET_SESSION_ID}`"
    )
    assert DIAGNOSTIC_REF in evidence_pull_suffix(TARGET_SESSION_ID, DIAGNOSTIC_REF)


def test_stored_listing_survives_a_read_back() -> None:
    conn = _connection()
    _pending_fetch(conn)
    job = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    ).jobs[0]
    listing = [
        {
            "name": "pid-1/yoke-pytest.raw.abc.log",
            "kind": "watcher",
            "size_bytes": 12,
            "modified_at": NOW,
        }
    ]

    report_relay_job(
        conn,
        actor_id=1,
        relay_id=OWNING_RELAY,
        job_kind="evidence",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="no_files",
        document={"files": listing},
        now="2026-08-22T12:00:07Z",
    )

    row = read_evidence_fetch(conn, FETCH_ID)
    assert json.loads(str(row["files"])) == listing
    # Nothing to read is an answer, not a failure.
    assert row["state"] == "succeeded"
