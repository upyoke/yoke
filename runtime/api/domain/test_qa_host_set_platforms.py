"""OS slots select one host per slot, and the driver slot drives the case."""

from unittest.mock import Mock

import pytest

from runtime.api.domain import qa_member_machine_partitions_test_support as support
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.qa_resume_machine import execution_machine


def _seed_case(test_db, tmp_path, monkeypatch, *, simultaneous, driver, hosts=None):
    replace_cases = support.replace_plan_cases

    def with_hosts(conn, **kwargs):
        for case in kwargs["cases"]:
            if hosts is not None:
                case["method_config"].pop("os", None)
                case["method_config"].pop("test_machines", None)
                case["method_config"].update(hosts)
        return replace_cases(conn, **kwargs)

    monkeypatch.setattr(support, "replace_plan_cases", with_hosts)
    support._seed(
        test_db, tmp_path, monkeypatch, simultaneous=simultaneous, driver=driver
    )


@pytest.mark.parametrize("driver", support.MACHINES)
def test_driver_slot_begins_and_resumes_with_its_companion(
    test_db, tmp_path, monkeypatch, driver
):
    _seed_case(test_db, tmp_path, monkeypatch, simultaneous=True, driver=driver)
    execution = support._begin(test_db)
    response = support._case_begin(execution)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, execution["id"])
    leases = execution_host_leases(test_db, current)
    assert {claim.target.test_machine for claim in leases} == set(support.MACHINES)
    lease = next(claim for claim in leases if claim.target.test_machine == driver)
    assert response.result_payload["execution"]["lease_id"] == lease.id
    resumed = support._case_begin(current)
    assert resumed.primary_success, resumed.error
    assert resumed.result_payload["execution"]["lease_id"] == lease.id


def test_slot_without_a_registered_host_refuses_and_takes_no_lease(
    test_db, tmp_path, monkeypatch
):
    _seed_case(
        test_db, tmp_path, monkeypatch, simultaneous=True, driver=None,
        hosts={"test_machines": [{"os": "windows"}, {"os": "macos", "driver": True}]},
    )
    execution = support._begin(test_db)
    response = support._case_begin(execution)
    assert not response.primary_success
    assert "test_machine_slots_unavailable" in response.error.message
    assert "windows" in response.error.message
    assert "register and verify" in response.error.message
    assert not execution_host_leases(test_db, execution)


def test_single_host_case_rejects_hosts_of_another_os(test_db, tmp_path, monkeypatch):
    _seed_case(
        test_db, tmp_path, monkeypatch, simultaneous=False, driver=None,
        hosts={"os": "windows"},
    )
    response = support._case_begin(support._begin(test_db))
    assert not response.primary_success
    assert "test_machine_platform_unavailable" in response.error.message


def test_slotted_resume_never_recovers_a_single_host():
    conn = Mock()
    case = {
        "method_config": {
            "test_machines": [{"os": "linux"}, {"os": "macos", "driver": True}]
        },
    }
    assert (
        execution_machine(conn, {"id": "resumed", "test_machine_lease_id": 42}, case) is None
    )
    conn.execute.assert_not_called()
