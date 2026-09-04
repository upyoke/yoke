"""Receipts and refusals for reset, bridge diagnosis, and the host kind."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.machine_operation_test_support import (
    MACHINE,
    operation_receipts,
    operation_request,
    run_operation,
)
from runtime.api.domain.machine_qa_baseline_group_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)
from yoke_contracts.machine_qa_terminal_bridge import TERMINAL_BRIDGE_CHECKS
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_capability import (
    test_machine_detail as machine_detail,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_host_operation_contract,
)


def test_reset_reaches_one_baseline_and_leaves_verification_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fresh box is still a proven one: the reset records beside the
    # verification row rather than into it.
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    control = FakeHostControl()

    submitted, execution = run_operation("reset", control=control)

    assert submitted.primary_success, submitted.error
    assert execution["baselines"] == ["fresh-host"]
    assert submitted.result_payload["operation"] == "reset"
    assert submitted.result_payload["status"] == "verified"
    assert control.full_reset_calls == 1
    [receipt] = operation_receipts(conn)
    assert receipt["operation"] == "reset"
    assert [check["name"] for check in receipt["checks"]] == ["fresh-host"]
    detail = machine_detail(conn, project="yoke", machine=MACHINE)
    assert detail["verification"]["status"] == "configured_unverified"


def test_reset_reaches_the_baseline_it_was_asked_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    submitted, execution = run_operation(
        "reset",
        control=FakeHostControl(),
        begin_payload={"baseline": "shell-preconfigured"},
    )

    assert submitted.primary_success, submitted.error
    assert execution["baselines"] == ["shell-preconfigured"]
    [receipt] = operation_receipts(conn)
    assert [check["name"] for check in receipt["checks"]] == ["shell-preconfigured"]


def test_reset_refuses_a_baseline_no_host_implements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    begun = handle_operation_begin(
        operation_request(
            {
                "project": "yoke",
                "operation": "reset",
                "baseline": "wiped-to-bare",
            }
        )
    )

    assert not begun.primary_success
    assert "not a registered host baseline" in begun.error.message
    assert "fresh-host" in begun.error.message


def test_a_failed_reset_records_the_error_it_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    submitted, _execution = run_operation(
        "reset",
        control=FakeHostControl(refuse_full_reset=True),
    )

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["status"] == "error"
    assert submitted.result_payload["error_code"] == "test_mac_reset_failed"
    [receipt] = operation_receipts(conn)
    assert receipt["status"] == "error"


def test_bridge_diagnosis_reports_every_capability_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    submitted, _execution = run_operation(
        "bridge_diagnose",
        control=FakeHostControl(),
    )

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["status"] == "verified"
    [receipt] = operation_receipts(conn)
    assert [check["name"] for check in receipt["checks"]] == list(
        TERMINAL_BRIDGE_CHECKS
    )


def test_a_capability_whose_precondition_failed_is_reported_as_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    submitted, _execution = run_operation(
        "bridge_diagnose",
        control=FakeHostControl(bridge_failure="system_events_control"),
    )

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["status"] == "error"
    [receipt] = operation_receipts(conn)
    rows = {check["name"]: check for check in receipt["checks"]}
    assert rows["system_events_control"]["recovery"]
    assert rows["window_launch"]["outcome"] == "not_run"
    assert "outcome" not in rows["ssh_transport"]


def test_submit_refuses_a_result_the_contract_never_asked_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    control = FakeHostControl()
    register_host_control_factory(lambda _material: control)
    try:
        begun = handle_operation_begin(
            operation_request({"project": "yoke", "operation": "reset"})
        )
        submission = execute_host_operation_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()
    payload = {"project": "yoke", **submission.payload}
    payload["checks"] = [{"name": "shell-preconfigured", "ok": True}]

    submitted = handle_operation_submit(operation_request(payload))

    assert not submitted.primary_success
    assert "must report exactly 'fresh-host'" in submitted.error.message
    assert not operation_receipts(conn)


def test_a_machine_declares_which_implementation_drives_it() -> None:
    # Settings that do not say what the host is would leave every operation
    # guessing, and the first wrong guess runs a destructive restore.
    with pytest.raises(TestMachineCapabilityError) as missing:
        validate_test_machine_settings(
            {
                key: value
                for key, value in TEST_MACHINE_SETTINGS.items()
                if key != "host_kind"
            }
        )

    assert "missing host_kind" in str(missing.value)

    with pytest.raises(TestMachineCapabilityError) as unknown:
        validate_test_machine_settings(
            {**TEST_MACHINE_SETTINGS, "host_kind": "linux-ssh"}
        )

    assert "host_kind must be one of mac-ssh" in str(unknown.value)
