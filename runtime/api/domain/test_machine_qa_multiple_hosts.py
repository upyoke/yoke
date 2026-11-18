"""Independent storage and admission across a project's Test Machine fleet."""

from __future__ import annotations

from runtime.api.domain.machine_qa_multiple_hosts_test_support import (
    MACHINES as MACHINES,
    _register_fleet as _register_fleet,
    _settings as _settings,
)


import json

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError as MachineCapabilityError,
)
from yoke_core.domain.machine_qa_case_machine import test_machine_requirement_kind as _machine_type
from yoke_contracts.machine_qa_execution import (
    HOST_BASELINES,
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


def test_each_machine_has_an_independent_read_and_verification_receipt() -> None:
    conn = make_conn()
    first, _second = _register_fleet(conn)

    listing = list_test_machines(conn)
    assert [row["test_machine"] for row in listing["test_machines"]] == list(MACHINES)
    with pytest.raises(MachineCapabilityError, match="pass --test-machine NAME"):
        read_test_machine_detail(conn)
    selected = read_test_machine_detail(
        conn,
        test_machine=MACHINES[1],
    )
    assert selected["test_machine"] == MACHINES[1]
    assert selected["concurrency"] == {
        "limit": 1,
        "mode": "serial",
        "scope": "machine",
    }

    for test_machine in MACHINES:
        record_test_machine_verification(
            conn,
            test_machine=test_machine,
            status="verified",
            checks=[{"name": "connection", "ok": True}],
            error_code=None,
        )
    updated = replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine=MACHINES[0],
        settings=_settings(MACHINES[0], notes="rack two"),
        base_settings=first["settings_token"],
    )

    assert updated["test_machine"] == MACHINES[0]
    statuses = {
        str(row["name"]): str(row["status"])
        for row in conn.execute(
            "SELECT m.name,v.status FROM test_machine_verifications v JOIN test_machines m ON m.id=v.test_machine_id"
        )
    }
    assert statuses == {
        MACHINES[0]: "configured_unverified",
        MACHINES[1]: "verified",
    }


def test_mission_admission_selects_the_first_free_machine() -> None:
    conn = make_conn()
    _register_fleet(conn)
    seed_qa_session(conn, "mission-one", "mission-two", "mission-three")
    for test_machine in MACHINES:
        record_test_machine_verification(
            conn,
            test_machine=test_machine,
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
        baselines=HOST_BASELINES,
    )
    assert first.settings["resource_name"] == MACHINES[0]
    assert read_fleet_context(conn) == {
        "state": "ready",
        "concurrency_mode": "serial_per_machine",
        "machines_total": 2,
        "machines_in_use": 1,
        "oses": ["macos"],
    }

    second = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="mission-two",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=HOST_BASELINES,
    )
    assert second.settings["resource_name"] == MACHINES[1]
    assert read_fleet_context(conn)["state"] == "in_use"
    with pytest.raises(MachineQaProtocolLeaseHeld):
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id="mission-three",
            operation="verify",
            checks=VERIFICATION_CHECKS,
            baselines=HOST_BASELINES,
        )

    release(conn, first.lease_id, "test-complete")
    next_contract = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="mission-three",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=HOST_BASELINES,
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
        test_machine=MACHINES[0],
        status="error",
        checks=[{"name": "terminal_bridge", "ok": False}],
        error_code="terminal_bridge_failed",
    )
    record_test_machine_verification(
        conn,
        test_machine=MACHINES[1],
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
        baselines=HOST_BASELINES,
    )
    assert automatic.settings["resource_name"] == MACHINES[1]
    assert automatic.selection_reason == f"selected {MACHINES[1]}: verified"

    pinned = begin_host_control_execution(
        conn,
        project="yoke",
        session_id="pinned",
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=HOST_BASELINES,
        test_machine=MACHINES[0],
    )
    assert pinned.settings["resource_name"] == MACHINES[0]
    assert "last verification error terminal_bridge_failed" in str(
        pinned.selection_reason
    )
    with pytest.raises(MachineCapabilityError, match="is unregistered"):
        begin_host_control_execution(
            conn,
            project="yoke",
            session_id="missing",
            operation="verify",
            checks=VERIFICATION_CHECKS,
            baselines=HOST_BASELINES,
            test_machine="mac-pro-missing",
        )
    release(conn, automatic.lease_id, "test-complete")
    release(conn, pinned.lease_id, "test-complete")


def test_a_selector_cannot_name_different_settings() -> None:
    conn = make_conn()
    _register_fleet(conn)

    with pytest.raises(MachineCapabilityError, match="does not match"):
        replace_test_machine_settings(
            conn,
            power_project="yoke",
            test_machine="mac-pro-lab",
            settings=_settings(MACHINES[0]),
            base_settings=None,
        )


def test_generic_capability_writes_cannot_register_a_machine() -> None:
    settings_json = json.dumps(_settings(MACHINES[0]))
    for kind in ("test-machine", _machine_type(MACHINES[0])):
        with pytest.raises(ValueError, match="use yoke test-machine settings-replace"):
            canonicalize_capability_settings(kind, settings_json)
