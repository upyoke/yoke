"""A fleet-busy waiter queues on the matching host with the shortest line."""

import pytest

from runtime.api.domain.machine_qa_host_test_support import verify_fixture_host
from runtime.api.domain.machine_qa_multiple_hosts_test_support import _settings
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
    begin_host_control_execution,
)
from yoke_core.domain.qa_host_turns import host_line, join_host_line
from yoke_core.domain.work_claim_targets import make_qa_admission_target

HOSTS = ("windows-native-lab", "windows-native-lab-2")
WINDOWS_CASE = {"instructions": "Run PowerShell", "method_config": {"os": "windows"}}


def _register_verified_windows_hosts(conn):
    for name in HOSTS:
        replace_test_machine_settings(
            conn,
            power_project="yoke",
            test_machine=name,
            settings={**_settings(name), "os": "windows"},
            base_settings=None,
        )
        verify_fixture_host(conn, name)


def _queue(conn, session_id: str) -> str:
    """Refuse one unpinned Windows case and queue it as the handler does."""
    with pytest.raises(MachineQaProtocolLeaseHeld) as refused:
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id=session_id,
            operation="case",
            cases=(WINDOWS_CASE,),
        )
    held = refused.value
    join_host_line(
        conn,
        make_qa_admission_target(held.test_machine),
        session_id=session_id,
        actor_id=1,
        resume_command=f"yoke qa requirement execute --session {session_id}",
    )
    return held.test_machine


def test_three_waiters_spread_across_two_busy_windows_hosts(test_db):
    _register_verified_windows_hosts(test_db)
    seed_qa_session(test_db, "holder-1", "holder-2", "w1", "w2", "w3")
    acquire(test_db, make_qa_admission_target(HOSTS[0]), "holder-1")
    acquire(test_db, make_qa_admission_target(HOSTS[1]), "holder-2")

    placed = [_queue(test_db, waiter) for waiter in ("w1", "w2", "w3")]

    # Equal lines tie on name; the next waiter takes the shorter line.
    assert placed == [HOSTS[0], HOSTS[1], HOSTS[0]]
    assert [w["session_id"] for w in host_line(test_db, HOSTS[0])] == ["w1", "w3"]
    assert [w["session_id"] for w in host_line(test_db, HOSTS[1])] == ["w2"]


def test_a_held_host_with_an_empty_line_beats_the_first_named_busy_host(test_db):
    """The live YOK-5545 shape: the first host is leased with a waiter, the
    second is held only by a session's hold-over and nobody waits for it."""
    _register_verified_windows_hosts(test_db)
    seed_qa_session(test_db, "walker", "queued", "setup", "w1")
    acquire(test_db, make_qa_admission_target(HOSTS[0]), "walker")
    join_host_line(
        test_db,
        make_qa_admission_target(HOSTS[0]),
        session_id="queued",
        actor_id=1,
        resume_command="yoke qa plan run --resume-execution-id queued",
    )
    acquire(
        test_db,
        make_qa_admission_target(HOSTS[1]),
        "setup",
        reason="qa-host-turn:holdover",
    )

    assert _queue(test_db, "w1") == HOSTS[1]
    assert [w["session_id"] for w in host_line(test_db, HOSTS[1])] == ["w1"]


def test_a_queued_waiter_keeps_its_line_on_retry(test_db):
    _register_verified_windows_hosts(test_db)
    seed_qa_session(test_db, "holder-1", "holder-2", "w1", "w2")
    acquire(test_db, make_qa_admission_target(HOSTS[0]), "holder-1")
    acquire(test_db, make_qa_admission_target(HOSTS[1]), "holder-2")
    assert _queue(test_db, "w1") == HOSTS[0]
    assert _queue(test_db, "w2") == HOSTS[1]

    # w1's own wait does not lengthen its line, so a retry stays put.
    assert _queue(test_db, "w1") == HOSTS[0]
    assert [w["session_id"] for w in host_line(test_db, HOSTS[0])] == ["w1"]
