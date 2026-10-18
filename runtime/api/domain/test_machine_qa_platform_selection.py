"""Case platforms constrain admission before verification rank or host leases."""

import pytest

from yoke_contracts.machine_qa_execution import HOST_BASELINES, VERIFICATION_CHECKS

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import make_conn
from runtime.api.domain.test_machine_qa_multiple_hosts import _register_fleet, _settings
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError as CapabilityError,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_case_platform import case_platform
from yoke_core.domain.machine_qa_execution_protocol import begin_host_control_execution
from yoke_core.domain.machine_qa_host_selection import (
    acquire_test_machine_admission,
    TestMachineFleetBusy as FleetBusy,
)


@pytest.mark.parametrize(
    "case",
    [
        {"instructions": "Run on a Linux Test Machine with the XFCE desktop."},
        {"method_id": "linux-terminal-check"},
        {"required_capability_kinds": ["linux-desktop"]},
        {
            "method_config": {
                "assertions": [
                    {"argv": ["/bin/bash", "-c", '/usr/bin/stat -c "%a" file']}
                ]
            }
        },
        {
            "method_config": {
                "baseline_configs": {"fresh-host": {"steps": ["xfce4-terminal"]}}
            }
        },
    ],
)
def test_linux_execution_inputs_require_linux(case):
    assert case_platform(case) == "linux"


@pytest.mark.parametrize(
    "os, instructions",
    [("macos", "Inspect Safari on macOS."), ("windows", "Run PowerShell on Windows.")],
)
def test_other_platforms(os, instructions):
    assert case_platform({"instructions": instructions}) == os


def test_expected_screen_text_does_not_pin_a_portable_case():
    assert (
        case_platform(
            {"method_config": {"expected_text": ["Linux", "Windows", "macOS"]}}
        )
        is None
    )


def _fleet():
    conn = make_conn()
    _register_fleet(conn)
    replace_test_machine_settings(
        conn,
        project="yoke",
        machine="z-linux",
        settings={**_settings("z-linux"), "os": "linux"},
        base_settings=None,
    )
    seed_qa_session(conn, "linux-one", "linux-two")
    return conn


def test_linux_case_never_leases_first_alphabetical_mac_host():
    conn = _fleet()
    contract = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="linux-one",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=HOST_BASELINES,
        host_cases=({"instructions": "Run on Linux", "method_config": {}},),
    )
    assert contract.settings["resource_name"] == "z-linux"
    with pytest.raises(FleetBusy):
        acquire_test_machine_admission(
            conn,
            project="yoke",
            session_id="linux-two",
            machine=None,
            select_any=True,
            cases=({"instructions": "Run on Linux"},),
        )


def test_explicit_mac_pin_cannot_override_linux_case():
    conn = _fleet()
    with pytest.raises(
        CapabilityError, match="test_machine_platform_unavailable.*linux"
    ):
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id="linux-one",
            operation="plan_case",
            machine="mac-mini-lab",
            cases=({"instructions": "Run on Linux"},),
        )


def test_no_matching_host_names_platform_and_recovery():
    conn = make_conn()
    _register_fleet(conn)
    seed_qa_session(conn, "linux-one")
    with pytest.raises(
        CapabilityError,
        match="test_machine_platform_unavailable.*Register and verify a linux",
    ):
        acquire_test_machine_admission(
            conn,
            project="yoke",
            session_id="linux-one",
            machine=None,
            select_any=True,
            cases=({"instructions": "Run on Linux"},),
        )


def test_empty_fleet_still_names_the_required_platform_and_recovery():
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    with pytest.raises(
        CapabilityError,
        match="test_machine_platform_unavailable.*Register and verify a linux",
    ):
        matching_platform_hosts([], ({"instructions": "Run on Linux"},))
