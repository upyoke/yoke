"""Every walk that needs a Test Machine waits in one queue, oldest eligible first."""

from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_host_test_support import verify_fixture_host
from runtime.api.domain.machine_qa_multiple_hosts_test_support import _settings
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _notices
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
    begin_host_control_execution,
)
from yoke_core.domain.qa_host_queue import queue_entries
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.steering_fleet_report_test_machines import (
    read_queue,
    reset_debt_lines,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target

WINDOWS = ("windows-native-lab", "windows-native-lab-2")
MAC = "mac-lab"
WINDOWS_CASE = {"instructions": "Run PowerShell", "method_config": {"os": "windows"}}


def _register_hosts(conn):
    for name, os in ((WINDOWS[0], "windows"), (WINDOWS[1], "windows"), (MAC, "macos")):
        replace_test_machine_settings(
            conn,
            power_project="yoke",
            test_machine=name,
            settings={**_settings(name), "os": os},
            base_settings=None,
        )
        verify_fixture_host(conn, name)


def _hold(conn, name, session_id):
    return acquire(conn, make_qa_admission_target(name), session_id)


def _refused(conn, session_id, *, test_machine=None):
    """Begin one Windows case while every eligible host is held."""
    with pytest.raises(MachineQaProtocolLeaseHeld) as refused:
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id=session_id,
            operation="case",
            test_machine=test_machine,
            cases=(WINDOWS_CASE,),
        )
    return refused.value


def _walk(conn, session_id, *, eligible=(), test_machine=None, slots=()):
    """Queue one plan execution as the plan-case handler does."""
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,'1',%s,'[]',0,'active',now(),now())",
        (execution_id, str(uuid4()), session_id, roster_digest([])),
    )
    row = query_one(
        conn, "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,)
    )
    execution = {**row, "roster": []}
    record_host_wait(
        conn,
        execution,
        test_machine=test_machine or eligible[0],
        rationale="all eligible hosts are in use",
        eligible=eligible,
        slots=slots,
    )
    return execution_id


def _reserved_for(conn, name):
    claim = active_claim(conn, make_qa_admission_target(name))
    return None if claim is None else claim.session_id


def test_an_unpinned_walk_is_eligible_for_every_matching_host(test_db):
    _register_hosts(test_db)
    seed_qa_session(test_db, "holder-1", "holder-2", "walker")
    _hold(test_db, WINDOWS[0], "holder-1")
    _hold(test_db, WINDOWS[1], "holder-2")

    assert _refused(test_db, "walker").eligible == WINDOWS


def test_a_pinned_or_resumed_walk_is_eligible_only_for_its_own_host(test_db):
    _register_hosts(test_db)
    seed_qa_session(test_db, "holder-1", "walker")
    _hold(test_db, WINDOWS[1], "holder-1")

    refused = _refused(test_db, "walker", test_machine=WINDOWS[1])

    assert refused.eligible == (WINDOWS[1],)


def test_a_freed_host_goes_to_the_oldest_waiter_it_can_serve(test_db, monkeypatch):
    _register_hosts(test_db)
    _notices(monkeypatch)
    seed_qa_session(test_db, "h-mac", "h-w1", "h-w2", "mac-walk", "win-1", "win-2")
    _hold(test_db, MAC, "h-mac")
    first = _hold(test_db, WINDOWS[0], "h-w1")
    second = _hold(test_db, WINDOWS[1], "h-w2")
    _walk(test_db, "mac-walk", eligible=(MAC,))
    _walk(test_db, "win-1", eligible=WINDOWS)
    _walk(test_db, "win-2", eligible=WINDOWS)

    # The Mac waiter at the front does not block a Windows host.
    release(test_db, second.id, "done")
    assert _reserved_for(test_db, WINDOWS[1]) == "win-1"

    # win-1 is served, so the next Windows host goes to win-2.
    release(test_db, first.id, "done")
    assert _reserved_for(test_db, WINDOWS[0]) == "win-2"
    assert [e["session_id"] for e in queue_entries(test_db)] == [
        "mac-walk",
        "win-1",
        "win-2",
    ]


def test_a_pinned_walk_waits_for_its_own_host(test_db, monkeypatch):
    _register_hosts(test_db)
    _notices(monkeypatch)
    seed_qa_session(test_db, "h-w1", "h-w2", "pinned", "any")
    _hold(test_db, WINDOWS[0], "h-w1")
    second = _hold(test_db, WINDOWS[1], "h-w2")
    _walk(test_db, "pinned", eligible=(WINDOWS[0],))
    _walk(test_db, "any", eligible=WINDOWS)

    release(test_db, second.id, "done")

    assert _reserved_for(test_db, WINDOWS[1]) == "any"
    assert [e["session_id"] for e in queue_entries(test_db)] == ["pinned", "any"]


def test_no_waiter_waits_while_an_eligible_host_is_idle(test_db, monkeypatch):
    _register_hosts(test_db)
    _notices(monkeypatch)
    seed_qa_session(test_db, "h-w1", "h-w2", "walker")
    first = _hold(test_db, WINDOWS[0], "h-w1")
    _hold(test_db, WINDOWS[1], "h-w2")
    _walk(test_db, "walker", eligible=WINDOWS)
    release(test_db, first.id, "done")
    assert _reserved_for(test_db, WINDOWS[0]) == "walker"

    # Taking the turn settles the walk's other host row; nobody else waits.
    taken = acquire(test_db, make_qa_admission_target(WINDOWS[0]), "walker")
    states = test_db.execute(
        "SELECT test_machine,state FROM qa_test_machine_waits WHERE session_id=%s "
        "ORDER BY test_machine",
        ("walker",),
    ).fetchall()

    assert taken.session_id == "walker"
    assert [(row["test_machine"], row["state"]) for row in states] == [
        (WINDOWS[0], "granted"),
        (WINDOWS[1], "cancelled"),
    ]
    assert queue_entries(test_db) == []


def test_a_reserved_walk_does_not_take_a_second_host(test_db, monkeypatch):
    _register_hosts(test_db)
    _notices(monkeypatch)
    seed_qa_session(test_db, "h-w1", "h-w2", "first", "second")
    one = _hold(test_db, WINDOWS[0], "h-w1")
    two = _hold(test_db, WINDOWS[1], "h-w2")
    _walk(test_db, "first", eligible=WINDOWS)
    _walk(test_db, "second", eligible=WINDOWS)

    release(test_db, one.id, "done")
    release(test_db, two.id, "done")

    assert _reserved_for(test_db, WINDOWS[0]) == "first"
    assert _reserved_for(test_db, WINDOWS[1]) == "second"


def test_the_fleet_report_shows_each_waiter_position_and_need(test_db, monkeypatch):
    _notices(monkeypatch)
    _register_hosts(test_db)
    seed_qa_session(test_db, "h-mac", "h-w1", "h-w2", "mac-walk", "win-walk")
    _hold(test_db, MAC, "h-mac")
    _hold(test_db, WINDOWS[0], "h-w1")
    _hold(test_db, WINDOWS[1], "h-w2")
    mac = _walk(test_db, "mac-walk", eligible=(MAC,))
    windows = _walk(test_db, "win-walk", eligible=WINDOWS)
    seed_qa_session(test_db, "mac-behind")
    release(test_db, active_claim(test_db, make_qa_admission_target(MAC)).id, "done")
    later = _walk(test_db, "mac-behind", eligible=(MAC,))

    lines = reset_debt_lines(read_queue(test_db))

    assert [line.split(" since ")[0] for line in lines] == [
        f"Test Machine queue: session mac-walk (execution {mac}) waits for {MAC} (1st for {MAC})",
        f"Test Machine queue: session win-walk (execution {windows}) waits for "
        f"any of {WINDOWS[0]}, {WINDOWS[1]} (1st for {WINDOWS[0]}, 1st for {WINDOWS[1]})",
        f"Test Machine queue: session mac-behind (execution {later}) waits for {MAC} (2nd for {MAC})",
    ]


def test_the_fleet_report_shows_one_host_per_slot(test_db, monkeypatch):
    _notices(monkeypatch)
    _register_hosts(test_db)
    seed_qa_session(test_db, "holder", "walker")
    for name in WINDOWS:
        _hold(test_db, name, "holder")
    execution = _walk(test_db, "walker", test_machine=WINDOWS[0], slots=(WINDOWS, (MAC,)))

    lines = reset_debt_lines(read_queue(test_db))

    assert [line.split(" since ")[0] for line in lines] == [
        f"Test Machine queue: session walker (execution {execution}) waits for one host per slot: "
        f"{MAC}; any of {WINDOWS[0]}, {WINDOWS[1]} (1st for {MAC}, "
        f"1st for {WINDOWS[0]}, 1st for {WINDOWS[1]})",
    ]
