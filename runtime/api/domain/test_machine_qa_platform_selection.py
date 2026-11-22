"""Case platforms constrain admission before verification rank or host leases."""

import pytest

from yoke_contracts.machine_qa_execution import HOST_BASELINES, VERIFICATION_CHECKS

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import make_conn
from runtime.api.domain.machine_qa_multiple_hosts_test_support import (
    _register_fleet,
    _settings,
)
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError as CapabilityError,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_case_platform import case_platform
from yoke_core.domain.machine_qa_execution_protocol import begin_host_control_execution
from yoke_core.domain.machine_verification_recording import record_test_machine_verification
from yoke_core.domain.machine_qa_host_selection import (
    acquire_test_machine_admission,
    TestMachineFleetBusy as FleetBusy,
)


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"os": "linux"}},
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
    assert (
        case_platform({"instructions": instructions, "method_config": {"os": os}}) == os
    )


def test_undeclared_platform_names_the_field_to_set():
    with pytest.raises(
        CapabilityError, match="test_machine_platform_undeclared.*method_config.os"
    ):
        case_platform(
            {
                "instructions": "Run on Linux",
                "method_config": {"expected_text": ["Linux", "Windows", "macOS"]},
            }
        )


def test_negative_linux_instruction_uses_declared_mac():
    from types import SimpleNamespace
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    host = SimpleNamespace(settings={"resource_name": "test-mac", "os": "macos"})
    case = {
        "instructions": "Do not use linux-lab; do not run stat -c",
        "method_config": {"os": "macos"},
    }
    assert case_platform(case) == "macos"
    assert matching_platform_hosts([host], [case]) == [host]


def _fleet():
    conn = make_conn()
    _register_fleet(conn)
    replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine="z-linux",
        settings={**_settings("z-linux"), "os": "linux"},
        base_settings=None,
    )
    record_test_machine_verification(
        conn,
        test_machine="z-linux",
        status="verified",
        checks=[{"name": "connection", "ok": True}],
        error_code=None,
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
        host_cases=(
            {"instructions": "Run on Linux", "method_config": {"os": "linux"}},
        ),
    )
    assert contract.settings["resource_name"] == "z-linux"
    with pytest.raises(FleetBusy):
        acquire_test_machine_admission(
            conn,
            project="yoke",
            session_id="linux-two",
            test_machine=None,
            select_any=True,
            cases=({"instructions": "Run on Linux", "method_config": {"os": "linux"}},),
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
            test_machine="mac-mini-lab",
            cases=({"instructions": "Run on Linux", "method_config": {"os": "linux"}},),
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
            test_machine=None,
            select_any=True,
            cases=({"instructions": "Run on Linux", "method_config": {"os": "linux"}},),
        )


def test_empty_fleet_still_names_the_required_platform_and_recovery():
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    with pytest.raises(
        CapabilityError,
        match="test_machine_platform_unavailable.*Register and verify a linux",
    ):
        matching_platform_hosts(
            [], ({"instructions": "Run on Linux", "method_config": {"os": "linux"}},)
        )


@pytest.mark.parametrize("value", ["plan9", [], None])
def test_invalid_platform_declaration_names_recovery(value):
    with pytest.raises(
        CapabilityError, match="test_machine_platform_invalid.*method_config.os"
    ):
        case_platform({"method_config": {"os": value}})


def test_slotted_case_platform_is_its_driver_slot_os():
    slots = [{"os": "linux"}, {"os": "macos", "driver": True}, {"os": "windows"}]
    assert case_platform({"method_config": {"test_machines": slots}}) == "macos"


def test_method_name_does_not_declare_platform():
    with pytest.raises(CapabilityError, match="test_machine_platform_undeclared"):
        case_platform({"method_id": "linux-terminal-check"})


def _windows_hosts():
    from types import SimpleNamespace

    return [
        SimpleNamespace(settings={"resource_name": "windows-lab", "os": "wsl"}),
        SimpleNamespace(settings={"resource_name": "windows-native-lab", "os": "windows"}),
    ]


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"os": "windows"}},
        {"method_config": {"command": "powershell -NoProfile -Command Get-Date"}},
    ],
)
def test_native_windows_case_selects_only_the_native_machine(case):
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    selected = matching_platform_hosts(_windows_hosts(), [case])
    assert [host.settings["resource_name"] for host in selected] == [
        "windows-native-lab"
    ]


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"os": "wsl"}},
        {"runner_id": "agent_mission", "method_config": {"executor": "informed_subagent", "os": "wsl"}},
    ],
)
def test_wsl_cases_keep_selecting_windows_lab(case):
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    selected = matching_platform_hosts(_windows_hosts(), [case])
    assert [host.settings["resource_name"] for host in selected] == ["windows-lab"]


def test_native_windows_case_refuses_a_wsl_only_fleet():
    from yoke_core.domain.machine_qa_case_platform import matching_platform_hosts

    with pytest.raises(
        CapabilityError, match=r"requires windows.*windows-lab \(wsl\)"
    ):
        matching_platform_hosts(
            _windows_hosts()[:1], [{"method_config": {"os": "windows"}}]
        )


def test_native_windows_contract_refuses_a_wsl_screenshot_receipt():
    from types import SimpleNamespace
    from yoke_core.domain.handlers.machine_qa_operation_result import (
        validate_operation_result,
    )

    receipt = SimpleNamespace(
        operation="screenshot",
        status="verified",
        error_code=None,
        artifacts=[],
        checks=[{"name": "screenshot", "ok": True, "os": "wsl"}],
    )
    with pytest.raises(ValueError, match="screenshot OS differs"):
        validate_operation_result(
            receipt, SimpleNamespace(settings={"os": "windows"})
        )


def test_wsl_windows_console_screenshot_receipt_passes_its_wsl_contract(monkeypatch):
    from types import SimpleNamespace
    from runtime.api.domain.test_windows_test_machine import wsl_console_screenshot
    from yoke_core.domain.handlers.machine_qa_operation_result import (
        validate_operation_result,
    )
    from yoke_core.domain.machine_qa_submission_artifacts import (
        MachineQaSubmissionArtifact,
    )
    from yoke_harness.test_machine_operations import OPERATION_RUNNERS

    control = SimpleNamespace(capture_screenshot=lambda: wsl_console_screenshot(monkeypatch))
    checks, error_code = OPERATION_RUNNERS["screenshot"](None, control, None)
    artifact = MachineQaSubmissionArtifact(**checks[0].pop("capture_artifact"))
    receipt = SimpleNamespace(
        operation="screenshot",
        status="verified" if error_code is None else "error",
        error_code=error_code,
        artifacts=[artifact],
        checks=checks,
        model_dump=lambda **_: {},
    )
    contract = SimpleNamespace(settings={"os": "wsl", "wsl_desktop_session": "windows"})
    validate_operation_result(receipt, contract)
    with pytest.raises(ValueError, match="screenshot OS differs"):
        validate_operation_result(receipt, SimpleNamespace(settings={"os": "windows"}))
