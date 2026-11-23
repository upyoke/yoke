"""A slotted case waits as one need per OS slot and takes every slot at once."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
    verify_fixture_host,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _notices
from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_case_machine import MachineConstraintError
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.qa_host_slot_turns import (
    assign_slot_hosts,
    slot_eligibility,
    slot_waits,
)
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.work_claim_targets import make_qa_admission_target

LINUX = ("linux-a", "linux-b")
TWO_LINUX = {
    "case_key": "two-linux",
    "method_config": {
        "test_machines": [{"os": "linux", "driver": True}, {"os": "linux"}]
    },
}


def _register(conn, name, os_name, tags=""):
    replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine=name,
        settings={
            **TEST_MACHINE_SETTINGS, "resource_name": name, "os": os_name,
            **({"capability_tags": tags} if tags else {}),
        },
        base_settings=None,
    )
    verify_fixture_host(conn, name)


@pytest.fixture
def linux_fleet(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    for name in LINUX:
        _register(test_db, name, "linux")
    seed_qa_session(test_db, "walker", "holder", messageable=True)
    return _notices(monkeypatch)


def _execution(conn, session_id):
    execution_id = str(uuid4())
    created = utc_now() - timedelta(minutes=1)
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,'item-qa',7,%s,'1',%s,'[]',0,'active',%s,%s)",
        (execution_id, str(uuid4()), session_id, roster_digest([]), created, created),
    )
    conn.commit()
    row = query_one(conn, "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,))
    return {**row, "roster": []}


def _waits(conn, execution_id):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT test_machine,state,queued_at,need_id FROM qa_test_machine_waits "
            "WHERE qa_plan_execution_id=%s ORDER BY test_machine",
            (execution_id,),
        ).fetchall()
    ]


def test_two_linux_slots_share_no_host_and_need_two_registered(test_db, linux_fleet):
    eligibility = slot_eligibility(test_db, TWO_LINUX, [TWO_LINUX])
    assert eligibility == (("linux", LINUX), ("linux", LINUX))
    # One host carries one live wait per session, so the hosts are dealt out.
    assert slot_waits(eligibility) == ((LINUX[0],), (LINUX[1],))
    three = {
        **TWO_LINUX,
        "method_config": {"test_machines": [*TWO_LINUX["method_config"]["test_machines"], {"os": "linux"}]},
    }
    with pytest.raises(TestMachineCapabilityError, match="test_machine_slots_unavailable.*register and verify"):
        slot_eligibility(test_db, three, [three])


def test_one_free_linux_host_acquires_nothing_and_both_waits_keep_their_place(
    test_db, linux_fleet
):
    busy = acquire(test_db, make_qa_admission_target(LINUX[1]), "holder")
    execution = _execution(test_db, "walker")
    record_host_wait(
        test_db, execution, test_machine=LINUX[0], rationale="slots busy",
        slots=slot_waits(slot_eligibility(test_db, TWO_LINUX, [TWO_LINUX])),
    )
    before = _waits(test_db, execution["id"])
    assert [(row[0], row[1]) for row in before] == [
        (LINUX[0], "waiting"), (LINUX[1], "waiting"),
    ]
    assert len({row[3] for row in before}) == 2 and len({row[2] for row in before}) == 1
    # The free host is not reserved alone; it stays free for the next waiter.
    assert active_claim(test_db, make_qa_admission_target(LINUX[0])) is None
    assert assign_slot_hosts(test_db, execution) is False
    assert _waits(test_db, execution["id"]) == before
    assert linux_fleet == []

    release(test_db, busy.id, "done")
    reserved = _waits(test_db, execution["id"])
    assert [(row[0], row[1]) for row in reserved] == [
        (LINUX[0], "reserved"), (LINUX[1], "reserved"),
    ]
    assert {row[2] for row in reserved} == {before[0][2]}
    for name in LINUX:
        assert active_claim(test_db, make_qa_admission_target(name)).session_id == "walker"
    # The execution is woken once, when every slot is reserved.
    assert len(linux_fleet) == 1


def test_two_free_linux_hosts_are_both_reserved_in_one_assignment(test_db, linux_fleet):
    execution = _execution(test_db, "walker")
    held = [acquire(test_db, make_qa_admission_target(name), "holder") for name in LINUX]
    record_host_wait(
        test_db, execution, test_machine=LINUX[0], rationale="slots busy",
        slots=slot_waits(slot_eligibility(test_db, TWO_LINUX, [TWO_LINUX])),
    )
    # Freed without serving the queue, as after an operator release.
    test_db.execute(
        "UPDATE work_claims SET released_at=now() WHERE id = ANY(%s)",
        ([claim.id for claim in held],),
    )
    assert assign_slot_hosts(test_db, execution) is True
    assert [(row[0], row[1]) for row in _waits(test_db, execution["id"])] == [
        (LINUX[0], "reserved"), (LINUX[1], "reserved"),
    ]
    assert len(linux_fleet) == 1


def _slotted(slots, tags):
    return {
        "case_key": "tagged",
        "method_config": {"test_machines": slots, "capability_tags": tags},
    }


MAC_AND_WINDOWS = [{"os": "macos"}, {"os": "windows", "driver": True}]


@pytest.fixture
def mixed_fleet(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _register(test_db, "win-a", "windows")
    _register(test_db, "mac-tagged", "macos", "macos:15")
    _register(test_db, "mac-tagged-2", "macos", "macos:15,extra:tag")


def test_os_tags_bind_only_that_os_slot(test_db, mixed_fleet):
    case = _slotted(MAC_AND_WINDOWS, {"macos": ["macos:15"]})
    assert slot_eligibility(test_db, case, [case]) == (
        ("macos", ("mac-tagged", "mac-tagged-2")),
        ("windows", ("win-a",)),
    )


@pytest.mark.parametrize("tags", [{"linux": ["macos:15"]}, ["macos:15"], []])
def test_slotted_tags_refuse_a_list_or_an_os_with_no_slot(test_db, mixed_fleet, tags):
    case = _slotted(MAC_AND_WINDOWS, tags)
    with pytest.raises(MachineConstraintError, match="test_machine_set_invalid.*macos:15"):
        slot_eligibility(test_db, case, [case])


def test_two_macos_slots_both_take_the_macos_tags(test_db, mixed_fleet):
    slots = [{"os": "macos"}, {"os": "macos"}, {"os": "windows", "driver": True}]
    case = _slotted(slots, {"macos": ["macos:15"]})
    tagged = ("mac-tagged", "mac-tagged-2")
    assert slot_eligibility(test_db, case, [case])[:2] == (("macos", tagged), ("macos", tagged))


def test_inheriting_case_tag_binds_every_slot_of_the_driver_os(test_db, mixed_fleet):
    slots = [{"os": "macos", "driver": True}, {"os": "macos"}, {"os": "windows"}]
    case = _slotted(slots, {"macos": ["macos:15"]})
    inheriting = {"case_key": "next", "method_config": {"capability_tags": ["extra:tag"]}}
    with pytest.raises(TestMachineCapabilityError, match="needs 2 verified macos.*extra:tag"):
        slot_eligibility(test_db, case, [case, inheriting])
    _register(test_db, "mac-tagged-3", "macos", "extra:tag,macos:15")
    assert slot_eligibility(test_db, case, [case, inheriting])[:2] == (
        ("macos", ("mac-tagged-2", "mac-tagged-3")),
        ("macos", ("mac-tagged-2", "mac-tagged-3")),
    )
