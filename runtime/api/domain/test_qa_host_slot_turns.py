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
from yoke_core.domain.machine_operation_recording import record_test_machine_operation
from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_command
from yoke_core.domain.machine_verification_recording import record_test_machine_verification
from yoke_core.domain.qa_host_health import host_unhealthy, unhealthy_rationale
from yoke_core.domain.qa_host_set_turns import record_host_wait
from yoke_core.domain.qa_host_slot_turns import (
    TestMachineSlotsBusy as SlotsBusy,
    assign_slot_hosts,
    select_slot_hosts,
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


def _register(conn, name, os_name, tags="", *, verified=True):
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
    if verified:
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
    # One host carries one live wait per execution, so the hosts are dealt out.
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
    with pytest.raises(SlotsBusy) as refused:
        select_slot_hosts(test_db, execution, TWO_LINUX, [TWO_LINUX])
    assert refused.value.test_machine == LINUX[1]
    record_host_wait(
        test_db, execution, test_machine=refused.value.test_machine,
        rationale=str(refused.value), slots=refused.value.slots,
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


def test_slotted_wait_names_the_leased_host_and_each_slot(test_db, mixed_fleet):
    seed_qa_session(test_db, "walker", "holder")
    execution = _execution(test_db, "walker")
    held = acquire(test_db, make_qa_admission_target("win-a"), "holder")
    case = _slotted(MAC_AND_WINDOWS, {"macos": ["macos:15"]})

    with pytest.raises(SlotsBusy) as refused:
        select_slot_hosts(test_db, execution, case, [case])

    busy = refused.value
    assert busy.test_machine == "win-a"
    assert str(busy) == (
        "no available host for every OS slot (macos, windows); "
        f"windows slot waits on win-a: lease {held.id} held by holder; "
        "free now: mac-tagged, mac-tagged-2"
    )
    waiting = record_host_wait(
        test_db, execution, test_machine=busy.test_machine, slots=busy.slots, rationale=str(busy),
    )
    assert waiting["host_wait"]["test_machine"] == "win-a"
    assert waiting["host_wait"]["rationale"] == str(busy)
    assert waiting["host_wait"]["waits_for"] == "one host per slot: any of mac-tagged, mac-tagged-2; win-a"


def test_slotted_wait_explains_failed_verification_and_resumes_after_repair(
    test_db, mixed_fleet, monkeypatch,
):
    _notices(monkeypatch)
    _register(test_db, "win-unverified", "windows", verified=False)
    seed_qa_session(test_db, "walker", messageable=True)
    execution = _execution(test_db, "walker")
    case = _slotted(MAC_AND_WINDOWS, {"macos": ["macos:15"]})
    record_test_machine_verification(
        test_db, test_machine="win-a", status="error",
        checks=[{"name": "verify", "ok": False}], error_code="ssh_unavailable",
    )

    with pytest.raises(SlotsBusy) as refused:
        select_slot_hosts(test_db, execution, case, [case])

    health = host_unhealthy(test_db, "win-a")
    assert health is not None
    busy = refused.value
    assert busy.test_machine == "win-a"
    assert f"windows slot waits on win-a: {unhealthy_rationale(health)}" in str(busy)
    assert busy.slots == (("mac-tagged", "mac-tagged-2"), ("win-a",))
    waiting = record_host_wait(
        test_db, execution, test_machine=busy.test_machine, slots=busy.slots, rationale=str(busy),
    )
    assert waiting["host_wait"]["state"] == "waiting"
    assert assign_slot_hosts(test_db, execution) is False

    verify_fixture_host(test_db, "win-a")

    assert assign_slot_hosts(test_db, execution) is True
    assert active_claim(test_db, make_qa_admission_target("win-a")).session_id == "walker"
    assert active_claim(test_db, make_qa_admission_target("win-unverified")) is None


def test_slotted_wait_blocks_on_failed_owed_reset_until_recovery(
    test_db, mixed_fleet, monkeypatch,
):
    notices = _notices(monkeypatch)
    seed_qa_session(test_db, "walker", "operator", messageable=True)
    execution = _execution(test_db, "walker")
    case = _slotted(MAC_AND_WINDOWS, {"macos": ["macos:15"]})
    target = make_qa_admission_target("win-a")
    held = acquire(test_db, target, "operator")
    record_reset_owed(
        test_db, case={"host_baseline": "fresh-host"},
        test_machine="win-a", lease_id=held.id,
    )
    record_test_machine_operation(
        test_db, test_machine="win-a", operation="reset", status="error",
        checks=[{"name": "fresh-host", "ok": False}], error_code="machine_fixture_failed",
        lease_id=held.id, contract_digest="",
    )
    release(test_db, held.id, "test-machine-reset-failed")

    with pytest.raises(SlotsBusy, match="machine_fixture_failed") as refused:
        select_slot_hosts(test_db, execution, case, [case])
    busy = refused.value
    assert reset_command("win-a", "fresh-host") in str(busy)
    record_host_wait(
        test_db, execution, test_machine=busy.test_machine, slots=busy.slots, rationale=str(busy),
    )
    assert assign_slot_hosts(test_db, execution) is False
    assert active_claim(test_db, target) is None
    assert notices == []

    healing = acquire(test_db, target, "operator")
    record_test_machine_operation(
        test_db, test_machine="win-a", operation="reset", status="verified",
        checks=[{"name": "fresh-host", "ok": True}], error_code=None,
        lease_id=healing.id, contract_digest="",
    )
    release(test_db, healing.id, "test-machine-reset-complete")

    assert active_claim(test_db, target).session_id == "walker"
    assert len(notices) == 1 and "QA host turn ready" in notices[0]
