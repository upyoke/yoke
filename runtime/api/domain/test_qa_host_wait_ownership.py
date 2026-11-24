"""Each execution keeps its host waits when the same session queues again."""

import pytest
from psycopg.errors import UniqueViolation

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import MACHINE, _notices
from runtime.api.domain.test_qa_host_holdover import _preflight
from runtime.api.domain.test_qa_host_set_turns import _execution, _row
from runtime.api.domain.test_qa_host_slot_turns import _register
from runtime.api.domain.test_qa_host_turns import _manual_acquire
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.qa_host_holdover import holdover_wait
from yoke_core.domain.qa_host_queue import queue_entries
from yoke_core.domain.qa_host_queue_steering import withdraw_manual_wait
from yoke_core.domain.qa_host_set_turns import (
    awaits_other_hosts,
    execution_waits,
    record_host_wait,
)
from yoke_core.domain.qa_host_slot_turns import assign_slot_hosts, slotted_wait
from yoke_core.domain.qa_host_turns import machine_waiters
from yoke_core.domain.work_claim_targets import make_qa_admission_target

LINUX, WINDOWS, MAC = MACHINE, "windows-native", "mac-lab"


@pytest.fixture
def fleet(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    for name, os_name in ((LINUX, "linux"), (WINDOWS, "windows"), (MAC, "macos")):
        _register(test_db, name, os_name)
    seed_qa_session(test_db, "walker", "holder", messageable=True)
    return _notices(monkeypatch)


def _queue(conn, execution_id, companion, reason):
    execution = _row(conn, execution_id, resume=True)
    record_host_wait(
        conn, execution, test_machine=WINDOWS, rationale=reason,
        slots=((companion,), (WINDOWS,)),
    )
    return execution


def _windows_wait(conn, execution_id):
    return next(
        wait for wait in execution_waits(conn, execution_id)
        if wait["test_machine"] == WINDOWS
    )


def test_same_session_slot_sets_keep_their_places_and_reservations(test_db, fleet):
    window_target = make_qa_admission_target(WINDOWS)
    busy = acquire(test_db, window_target, "holder")
    older_id, later_id = (_execution(test_db, "walker") for _ in range(2))
    older = _queue(test_db, older_id, LINUX, "Linux and Windows")
    original = _windows_wait(test_db, older_id)
    _queue(test_db, later_id, MAC, "Mac and Windows")
    later_waits = execution_waits(test_db, later_id)

    assert _windows_wait(test_db, older_id) == original
    assert original["rationale"] == "Linux and Windows"
    assert original["queued_at"] < _windows_wait(test_db, later_id)["queued_at"]
    assert [(row["execution_id"], row["test_machines"]) for row in queue_entries(test_db)] == [
        (older_id, sorted((LINUX, WINDOWS))), (later_id, sorted((MAC, WINDOWS))),
    ]
    older_waits = execution_waits(test_db, older_id)
    assert len({row["need_id"] for row in older_waits}) == 2
    assert all(slotted_wait(test_db, row) for row in older_waits)
    assert all(awaits_other_hosts(test_db, row) for row in older_waits)
    assert assign_slot_hosts(test_db, older) is False
    assert active_claim(test_db, make_qa_admission_target(LINUX)) is None
    assert fleet == []

    release(test_db, busy.id, "Windows free")
    assert {row["state"] for row in execution_waits(test_db, older_id)} == {"reserved"}
    reserved = _windows_wait(test_db, older_id)
    assert reserved["claim_id"] == active_claim(test_db, window_target).id
    assert execution_waits(test_db, later_id) == later_waits
    assert len(fleet) == 1
    assert f"--resume-execution-id {older_id}" in fleet[0]

    _queue(test_db, older_id, LINUX, "Linux and Windows")
    assert execution_waits(test_db, later_id) == later_waits
    _queue(test_db, later_id, MAC, "Mac and Windows")
    assert _windows_wait(test_db, older_id)["claim_id"] == reserved["claim_id"]
    assert _windows_wait(test_db, older_id)["state"] == "reserved"
    assert _windows_wait(test_db, later_id)["state"] == "waiting"
    assert len(fleet) == 1


def test_execution_takes_up_its_sessions_holdover(test_db, fleet):
    acquire(test_db, make_qa_admission_target(WINDOWS), "holder")
    _preflight(test_db, "walker")
    holdover = holdover_wait(test_db, active_claim(test_db, make_qa_admission_target(LINUX)))
    assert holdover["state"] == "reserved"
    assert holdover["qa_plan_execution_id"] is None

    execution_id = _execution(test_db, "walker")
    _queue(test_db, execution_id, LINUX, "Linux and Windows")

    [adopted] = [
        wait for wait in execution_waits(test_db, execution_id)
        if wait["test_machine"] == LINUX
    ]
    assert adopted["qa_plan_execution_id"] == execution_id
    for key in ("id", "claim_id", "queued_at", "state"):
        assert adopted[key] == holdover[key]
    assert awaits_other_hosts(test_db, adopted)
    assert fleet == []


def test_manual_acquire_and_withdraw_leave_execution_wait_intact(
    test_db, fleet, monkeypatch,
):
    acquire(test_db, make_qa_admission_target(LINUX), "holder")
    execution_id = _execution(test_db, "walker")
    record_host_wait(
        test_db, _row(test_db, execution_id), test_machine=LINUX,
        rationale="Needs both slots", slots=((LINUX,), (WINDOWS,)),
    )
    [original] = machine_waiters(test_db, LINUX)
    assert original["need_id"]

    refused = _manual_acquire(test_db, monkeypatch, "walker")

    assert refused.error.code == "claim_held"
    execution_wait, manual_wait = machine_waiters(test_db, LINUX)
    assert execution_wait == original
    assert manual_wait["qa_plan_execution_id"] is None
    assert withdraw_manual_wait(test_db, "walker", LINUX, 1)["wait_id"] == manual_wait["id"]
    assert machine_waiters(test_db, LINUX) == [original]


def test_index_rejects_duplicate_live_execution_wait_even_under_another_session(
    test_db, fleet,
):
    acquire(test_db, make_qa_admission_target(WINDOWS), "holder")
    execution_id = _execution(test_db, "walker")
    _queue(test_db, execution_id, LINUX, "Linux and Windows")
    wait = _windows_wait(test_db, execution_id)

    with pytest.raises(UniqueViolation, match="idx_qa_test_machine_waits_live_owner"):
        test_db.execute(
            "INSERT INTO qa_test_machine_waits "
            "(id,test_machine,session_id,actor_id,queued_at,qa_plan_execution_id,state,resume_command) "
            "VALUES ('duplicate',%s,'holder',1,now(),%s,'waiting','resume')",
            (wait["test_machine"], execution_id),
        )
    test_db.rollback()
