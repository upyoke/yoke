"""Platform requirements apply to a simultaneous set without changing its driver."""

from unittest.mock import Mock

import pytest

from runtime.api.domain import test_qa_member_machine_partitions as support
from runtime.api.domain.machine_qa_host_test_support import TEST_MACHINE_SETTINGS
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.qa_resume_machine import execution_machine


def _seed_case(test_db, tmp_path, monkeypatch, *, simultaneous, instructions, linux):
    replace_cases = support.replace_plan_cases

    def with_instructions(conn, **kwargs):
        for case in kwargs["cases"]:
            case["instructions"] = instructions
        return replace_cases(conn, **kwargs)

    monkeypatch.setattr(support, "replace_plan_cases", with_instructions)
    support._seed(
        test_db,
        tmp_path,
        monkeypatch,
        simultaneous=simultaneous,
        driver=support.MACHINES[1],
    )
    if linux:
        replace_test_machine_settings(
            test_db,
            project="yoke",
            machine=support.MACHINES[0],
            settings={**TEST_MACHINE_SETTINGS, "os": "linux"},
            base_settings=None,
        )


@pytest.mark.parametrize("instructions", ["Inspect linux-lab.", "Run a Linux check."])
def test_macos_driver_begins_and_resumes_with_linux_companion(
    test_db,
    tmp_path,
    monkeypatch,
    instructions,
):
    _seed_case(
        test_db,
        tmp_path,
        monkeypatch,
        simultaneous=True,
        instructions=instructions,
        linux=True,
    )
    execution = support._begin(test_db)
    response = support._case_begin(execution)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, execution["id"])
    leases = execution_host_leases(test_db, current)
    assert {claim.target.machine_id for claim in leases} == set(support.MACHINES)
    driver = next(
        claim for claim in leases if claim.target.machine_id == support.MACHINES[1]
    )
    assert response.result_payload["execution"]["lease_id"] == driver.id
    resumed = support._case_begin(current)
    assert resumed.primary_success, resumed.error
    assert resumed.result_payload["execution"]["lease_id"] == driver.id


def test_missing_platform_names_full_set_and_rolls_back_leases(
    test_db,
    tmp_path,
    monkeypatch,
):
    _seed_case(
        test_db,
        tmp_path,
        monkeypatch,
        simultaneous=True,
        instructions="Run a Linux check.",
        linux=False,
    )
    execution = support._begin(test_db)
    response = support._case_begin(execution)
    assert not response.primary_success
    assert "test_machine_platform_unavailable" in response.error.message
    assert all(name in response.error.message for name in support.MACHINES)
    assert "Register and verify" in response.error.message
    assert not execution_host_leases(test_db, execution)


def test_single_host_linux_case_still_rejects_macos(test_db, tmp_path, monkeypatch):
    _seed_case(
        test_db,
        tmp_path,
        monkeypatch,
        simultaneous=False,
        instructions="Run a Linux check.",
        linux=False,
    )
    response = support._case_begin(support._begin(test_db))
    assert not response.primary_success
    assert "test_machine_platform_unavailable" in response.error.message


def test_multi_host_resume_never_recovers_a_companion_override():
    conn = Mock()
    case = {
        "instructions": "Inspect linux-lab.",
        "method_config": {"machine": "test-mac", "machines": ["linux-lab", "test-mac"]},
    }
    assert (
        execution_machine(conn, {"id": "resumed", "machine_lease_id": 42}, case) is None
    )
    conn.execute.assert_not_called()
