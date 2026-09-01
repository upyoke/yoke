"""Independent storage and admission across a project's Test Mac fleet."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError as MachineCapabilityError,
    test_machine_capability_type as _machine_type,
)
from yoke_contracts.machine_qa_execution import (
    VERIFICATION_BASELINES,
    VERIFICATION_CHECKS,
)
from yoke_core.domain.coordination_claims import release
from yoke_core.domain.machine_qa_capability import (
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
    test_machine_list as list_test_machines,
)
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
    begin_host_control_execution,
)
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)
from yoke_core.domain.qa_test_machine_capability_context import (
    test_machine_capability_context as read_fleet_context,
)
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)


MACHINES = ("mac-mini-lab", "mac-studio-lab")


def _settings(machine: str, *, notes: str = "") -> dict[str, str]:
    return {
        "resource_name": machine,
        "host": f"{machine}.local",
        "user": "yoke-test",
        "operating_notes": notes,
    }


def _register_fleet(conn):
    first = replace_test_machine_settings(
        conn,
        project="yoke",
        settings=_settings(MACHINES[0]),
        base_settings=None,
    )
    second = replace_test_machine_settings(
        conn,
        project="yoke",
        machine=MACHINES[1],
        settings=_settings(MACHINES[1]),
        base_settings=None,
    )
    return first, second


def test_each_machine_has_an_independent_read_and_verification_receipt() -> None:
    conn = make_conn()
    first, _second = _register_fleet(conn)

    listing = list_test_machines(conn, project="yoke")
    assert [row["machine"] for row in listing["machines"]] == list(MACHINES)
    assert [row["capability_type"] for row in listing["machines"]] == [
        _machine_type(machine) for machine in MACHINES
    ]
    with pytest.raises(MachineCapabilityError, match="pass --machine NAME"):
        read_test_machine_detail(conn, project="yoke")
    selected = read_test_machine_detail(
        conn,
        project="yoke",
        machine=MACHINES[1],
    )
    assert selected["machine"] == MACHINES[1]
    assert selected["concurrency"] == {
        "limit": 1,
        "mode": "serial",
        "scope": "machine",
    }

    for machine in MACHINES:
        record_test_machine_verification(
            conn,
            1,
            machine=machine,
            status="verified",
            checks=[{"name": "connection", "ok": True}],
            error_code=None,
        )
    with pytest.raises(MachineCapabilityError, match="multiple test machines"):
        replace_test_machine_settings(
            conn,
            project="yoke",
            settings=_settings(MACHINES[0], notes="rack two"),
            base_settings=first["settings_token"],
        )
    updated = replace_test_machine_settings(
        conn,
        project="yoke",
        machine=MACHINES[0],
        settings=_settings(MACHINES[0], notes="rack two"),
        base_settings=first["settings_token"],
    )

    assert updated["machine"] == MACHINES[0]
    statuses = {
        str(row["capability_type"]): str(row["status"])
        for row in conn.execute(
            "SELECT capability_type,status FROM test_machine_verifications"
        )
    }
    assert statuses == {
        _machine_type(MACHINES[0]): "configured_unverified",
        _machine_type(MACHINES[1]): "verified",
    }


def test_mission_admission_selects_the_first_free_machine() -> None:
    conn = make_conn()
    _register_fleet(conn)
    seed_qa_session(conn, "mission-one", "mission-two", "mission-three")
    for machine in MACHINES:
        record_test_machine_verification(
            conn,
            1,
            machine=machine,
            status="verified",
            checks=[{"name": "connection", "ok": True}],
            error_code=None,
        )

    first = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="mission-one",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
    )
    assert first.settings["resource_name"] == MACHINES[0]
    assert read_fleet_context(conn, project_id=1) == {
        "state": "ready",
        "concurrency_mode": "serial_per_machine",
        "machines_total": 2,
        "machines_in_use": 1,
    }

    second = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="mission-two",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
    )
    assert second.settings["resource_name"] == MACHINES[1]
    assert read_fleet_context(conn, project_id=1)["state"] == "in_use"
    with pytest.raises(MachineQaProtocolLeaseHeld):
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id="mission-three",
            operation="verify",
            checks=VERIFICATION_CHECKS,
            baselines=VERIFICATION_BASELINES,
        )

    release(conn, first.lease_id, "test-complete")
    next_contract = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="mission-three",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
    )
    assert next_contract.settings["resource_name"] == MACHINES[0]
    release(conn, second.lease_id, "test-complete")
    release(conn, next_contract.lease_id, "test-complete")


def test_admission_prefers_verified_then_honors_an_explicit_pin() -> None:
    conn = make_conn()
    _register_fleet(conn)
    seed_qa_session(conn, "automatic", "pinned", "missing")
    record_test_machine_verification(
        conn,
        1,
        machine=MACHINES[0],
        status="error",
        checks=[{"name": "terminal_bridge", "ok": False}],
        error_code="terminal_bridge_failed",
    )
    record_test_machine_verification(
        conn,
        1,
        machine=MACHINES[1],
        status="verified",
        checks=[{"name": "connection", "ok": True}],
        error_code=None,
    )

    automatic = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="automatic",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
    )
    assert automatic.settings["resource_name"] == MACHINES[1]
    assert automatic.selection_reason == f"selected {MACHINES[1]}: verified"

    pinned = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="pinned",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
        machine=MACHINES[0],
    )
    assert pinned.settings["resource_name"] == MACHINES[0]
    assert "last verification error terminal_bridge_failed" in str(
        pinned.selection_reason
    )
    with pytest.raises(MachineCapabilityError, match="has no test machine"):
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id="missing",
            operation="verify",
            checks=VERIFICATION_CHECKS,
            baselines=VERIFICATION_BASELINES,
            machine="mac-pro-missing",
        )
    release(conn, automatic.lease_id, "test-complete")
    release(conn, pinned.lease_id, "test-complete")


def test_a_selector_cannot_name_different_settings() -> None:
    conn = make_conn()
    _register_fleet(conn)

    with pytest.raises(MachineCapabilityError, match="does not match"):
        replace_test_machine_settings(
            conn,
            project="yoke",
            machine="mac-pro-lab",
            settings=_settings(MACHINES[0]),
            base_settings=None,
        )


def test_generic_capability_writes_require_the_machine_suffix() -> None:
    settings_json = json.dumps(_settings(MACHINES[0]))

    with pytest.raises(ValueError, match="test-machine:<name>"):
        canonicalize_capability_settings("test-machine", settings_json)
    with pytest.raises(ValueError, match="must be"):
        canonicalize_capability_settings(
            _machine_type(MACHINES[1]),
            settings_json,
        )
    assert (
        json.loads(
            canonicalize_capability_settings(
                _machine_type(MACHINES[0]),
                settings_json,
            )
        )["resource_name"]
        == MACHINES[0]
    )
