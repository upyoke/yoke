"""Cases select hosts by OS or slots; inherit cases keep their opener's hosts."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_member_machine_partitions_test_support import (
    SESSION,
    _begin,
    _case_begin,
    seed_fleet_cases,
)
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain import qa_host_slot_turns
from yoke_core.domain.qa_host_set_turns import execution_waits
from yoke_core.domain.qa_plan_case_chain import INHERITED_PREDECESSOR_NOT_PASSED
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MAC, STUDIO = "mac-mini-lab", "mac-studio-lab"
SLOTS = [{"os": "linux"}, {"os": "macos", "driver": True}, {"os": "windows"}]


def _host(response):
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready", response.result_payload
    return response.result_payload["execution"]["settings"]["resource_name"]


def _pass(conn, execution, ordinal):
    current = lock_plan_execution(conn, execution["id"])
    case = current["roster"][ordinal]
    advance_plan_execution(
        conn, current, ordinal=ordinal, requirement_id=case["requirement_id"],
        result={"requirement_id": case["requirement_id"], "case_outcome": "passed"},
    )
    return lock_plan_execution(conn, execution["id"])


@pytest.fixture
def no_selection(monkeypatch):
    """Fail any host selection; inherit cases only continue on held hosts."""
    calls = []

    def refuse(*args, **kwargs):
        calls.append(kwargs.get("test_machine"))
        raise AssertionError("an inherit case selected a host")

    def arm():
        for target in (
            "yoke_core.domain.machine_qa_execution_protocol.acquire_test_machine_admission",
            "yoke_core.domain.machine_qa_host_selection.acquire_test_machine_admission",
            "yoke_core.domain.qa_host_slot_turns.select_slot_hosts",
        ):
            monkeypatch.setattr(target, refuse)

    return arm


def test_os_case_admits_on_the_idle_identical_host_without_a_single_host_wait(
    test_db, tmp_path, monkeypatch
):
    fleet = {"windows-native-lab": "windows", "windows-native-lab-2": "windows"}
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch, fleet,
        [{"case_key": "windows-check", "hosts": {"os": "windows"}}],
    )
    seed_qa_session(test_db, SESSION, "busy-holder", messageable=True)
    acquire(test_db, make_qa_admission_target("windows-native-lab"), "busy-holder")
    execution = _begin(test_db)
    assert _host(_case_begin(execution)) == "windows-native-lab-2"
    assert execution_waits(test_db, execution["id"]) == []


def test_slot_case_is_admitted_on_one_host_per_slot(test_db, tmp_path, monkeypatch):
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch, {"linux-lab": "linux", "windows-lab": "windows"},
        [{"case_key": "three-os", "hosts": {"test_machines": SLOTS}}],
    )
    execution = _begin(test_db)
    response = _case_begin(execution)
    assert _host(response) == MAC
    leases = {
        str(claim.target.test_machine): claim.id
        for claim in execution_host_leases(test_db, lock_plan_execution(test_db, execution["id"]))
    }
    assert set(leases) == {"linux-lab", MAC, "windows-lab"}
    assert response.result_payload["execution"]["lease_id"] == leases[MAC]


def test_slotted_wait_names_the_host_refused_after_selection(test_db, tmp_path, monkeypatch):
    windows = "windows-lab"
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch, {"linux-lab": "linux", windows: "windows"},
        [{"case_key": "three-os", "hosts": {"test_machines": SLOTS}}],
    )
    seed_qa_session(test_db, SESSION, "holder", messageable=True)
    held = acquire(test_db, make_qa_admission_target(windows), "holder")
    execution = _begin(test_db)
    unavailable = qa_host_slot_turns._unavailable
    missed_lease = False

    def before_lease(conn, name):
        nonlocal missed_lease
        if name == windows and not missed_lease:
            missed_lease = True
            return None
        return unavailable(conn, name)

    monkeypatch.setattr(qa_host_slot_turns, "_unavailable", before_lease)

    response = _case_begin(execution)

    assert response.primary_success, response.error
    result = response.result_payload
    assert result["state"] == "waiting", result
    assert result["host_wait"]["test_machine"] == windows
    assert active_claim(test_db, make_qa_admission_target(windows)).id == held.id
    assert active_claim(test_db, make_qa_admission_target("linux-lab")) is None


def test_inherit_chain_runs_on_the_openers_host_while_an_identical_host_idles(
    test_db, tmp_path, monkeypatch, no_selection
):
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch, {STUDIO: "macos"},
        [
            {"case_key": "opener", "hosts": {"os": "macos"}},
            {"case_key": "first-follower", "inherit": True, "hosts": {"os": "macos"}},
            {"case_key": "second-follower", "inherit": True, "hosts": {"os": "macos"}},
        ],
    )
    execution = _begin(test_db)
    opener = _host(_case_begin(execution))
    idle = ({MAC, STUDIO} - {opener}).pop()
    no_selection()
    for ordinal in (1, 2):
        execution = _pass(test_db, execution, ordinal - 1)
        assert _host(_case_begin(execution, ordinal)) == opener
        assert active_claim(test_db, make_qa_admission_target(idle)) is None


def test_slotted_chain_resumes_on_its_driver_and_companions(
    test_db, tmp_path, monkeypatch, no_selection
):
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch, {"linux-lab": "linux", "windows-lab": "windows"},
        [
            {"case_key": "opener", "hosts": {"test_machines": SLOTS}},
            {"case_key": "follower", "inherit": True, "hosts": {"test_machines": SLOTS}},
        ],
    )
    execution = _begin(test_db)
    first = _case_begin(execution)
    assert _host(first) == MAC
    leases = [claim.id for claim in execution_host_leases(test_db, execution)]
    execution = _pass(test_db, execution, 0)
    no_selection()
    begun = _case_begin(execution, 1)
    assert _host(begun) == MAC
    # Interrupted mid-case, the follower resumes on the same three leases.
    resumed = _case_begin(lock_plan_execution(test_db, execution["id"]), 1)
    assert resumed.result_payload["execution"]["lease_id"] == first.result_payload[
        "execution"
    ]["lease_id"]
    assert [claim.id for claim in execution_host_leases(test_db, execution)] == leases


def _blocked(response):
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "blocked", response.result_payload
    result = response.result_payload["result"]
    assert result["case_outcome"] == "blocked_on_precondition"
    return result


@pytest.mark.parametrize("slotted", [False, True])
def test_lost_custody_blocks_the_follower_without_selecting_a_host(
    test_db, tmp_path, monkeypatch, no_selection, slotted
):
    hosts = {"test_machines": SLOTS} if slotted else {"os": "macos"}
    seed_fleet_cases(
        test_db, tmp_path, monkeypatch,
        {"linux-lab": "linux", "windows-lab": "windows", STUDIO: "macos"},
        [
            {"case_key": "opener", "hosts": hosts},
            {"case_key": "follower", "inherit": True, "hosts": hosts},
            {"case_key": "tail", "inherit": True, "hosts": hosts},
        ],
    )
    execution = _begin(test_db)
    _host(_case_begin(execution))
    execution = _pass(test_db, execution, 0)
    if slotted:
        # One slot's lease is gone.
        companion = next(
            claim for claim in execution_host_leases(test_db, execution)
            if claim.target.test_machine == "linux-lab"
        )
        release(test_db, companion.id, "taken")
    else:
        # No lease and no run evidence: the chain has no recorded host.
        release(test_db, int(execution["test_machine_lease_id"]), "taken")
        test_db.execute(
            "UPDATE qa_plan_executions SET test_machine_lease_id=NULL WHERE id=%s",
            (execution["id"],),
        )
        test_db.commit()
    no_selection()
    result = _blocked(_case_begin(lock_plan_execution(test_db, execution["id"]), 1))
    assert INHERITED_PREDECESSOR_NOT_PASSED in str(result)
    assert "restarts from 'opener'" in result["error"]
    # Its follower is blocked too; the next run restarts the chain from the opener.
    _blocked(_case_begin(lock_plan_execution(test_db, execution["id"]), 2))
