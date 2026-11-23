"""Automatic QA uses a healthy, verified host of the required type."""

import pytest

from runtime.api.domain.machine_qa_multiple_hosts_test_support import _settings
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import make_conn
from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_host_selection import (
    TestMachineFleetBusy as FleetBusy,
    acquire_test_machine_admission,
)
from yoke_core.domain.machine_verification_recording import record_test_machine_verification
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)

FIRST = "windows-native-lab"
SECOND = "windows-native-lab-2"


def _fleet(first_status, second_status, *, second_tags=None):
    conn = make_conn()
    seed_qa_session(conn, "first", "second")
    for name, status in ((FIRST, first_status), (SECOND, second_status)):
        settings = {**_settings(name), "os": "windows"}
        if name == SECOND and second_tags:
            settings["capability_tags"] = second_tags
        replace_test_machine_settings(
            conn, power_project="yoke", settings=settings, base_settings=None
        )
        if status:
            record_test_machine_verification(
                conn,
                test_machine=name,
                status=status,
                checks=[{"name": "connection", "ok": status == "verified"}],
                error_code="connection_failed" if status == "error" else None,
            )
    return conn


def _admit(conn, session, *, tags=None, pin=None):
    config = {"os": "windows"}
    if tags is not None:
        config["capability_tags"] = tags
    return acquire_test_machine_admission(
        conn,
        project="yoke",
        session_id=session,
        test_machine=pin,
        select_any=True,
        cases=({"method_config": config},),
    ).lease.target.test_machine


def test_busy_windows_host_leaves_other_verified_windows_host_available():
    conn = _fleet("verified", "verified")
    assert _admit(conn, "first") == FIRST
    assert _admit(conn, "second") == SECOND


@pytest.mark.parametrize("status", [None, "error"])
def test_automatic_qa_waits_for_busy_verified_host_instead_of_using_unready_host(status):
    conn = _fleet("verified", status)
    assert _admit(conn, "first") == FIRST
    with pytest.raises(FleetBusy) as exc:
        _admit(conn, "second")
    assert [candidate.test_machine for candidate in exc.value.busy] == [FIRST]


def test_never_verified_fleet_names_the_recovery():
    conn = _fleet(None, None)
    with pytest.raises(TestMachineCapabilityError, match="test_machine_no_verified_host"):
        _admit(conn, "first")


def test_all_tags_must_match_and_explicit_pins_cannot_override_them():
    conn = _fleet("verified", "verified", second_tags="arch:x64, codex-desktop-signed-in")
    tags = ["arch:x64", "codex-desktop-signed-in"]
    with pytest.raises(
        TestMachineCapabilityError,
        match="test_machine_capability_tags_unavailable.*codex-desktop-signed-in",
    ):
        _admit(conn, "first", tags=tags, pin=FIRST)
    assert _admit(conn, "first", tags=tags) == SECOND


def test_mission_authoring_normalizes_tags_and_refuses_a_named_host():
    config = validate_method_config(
        "agent-mission",
        {
            "executor": "informed_subagent",
            "os": "windows",
            "capability_tags": ["arch:x64", " arch:x64 "],
        },
    )
    assert config["capability_tags"] == ["arch:x64"]
    with pytest.raises(QaMethodConfigError, match="test_machine_capability_tags_invalid"):
        validate_method_config(
            "agent-mission",
            {
                "executor": "informed_subagent",
                "os": "windows",
                "capability_tags": {"windows": ["arch:x64"]},
            },
        )
    with pytest.raises(QaMethodConfigError, match="test_machine_name_forbidden"):
        validate_method_config(
            "agent-mission",
            {"executor": "informed_subagent", "test_machine": FIRST},
        )


@pytest.mark.parametrize("pin", [None, SECOND])
def test_replacement_admits_other_windows_host_while_predecessor_host_is_busy(
    monkeypatch, pin
):
    import json

    from yoke_contracts.machine_qa_execution import HOST_BASELINES, VERIFICATION_CHECKS
    from yoke_core.domain.qa_plan_host_leases import begin_case_host_contract

    conn = _fleet("verified", "verified")
    assert _admit(conn, "first") == FIRST
    conn.executescript(
        """
        CREATE TABLE qa_requirements (
            id INTEGER, replacement_requirement_id INTEGER, superseded_by_requirement_id INTEGER
        );
        CREATE TABLE qa_runs (
            id INTEGER, qa_requirement_id INTEGER, created_at TEXT, raw_result TEXT
        );
        CREATE TABLE qa_plan_execution_results (
            execution_id TEXT, ordinal INTEGER, result_json TEXT
        );
        CREATE TABLE qa_plan_executions (
            id TEXT, state TEXT, test_machine_lease_id INTEGER, heartbeat_at TEXT
        );
        INSERT INTO qa_requirements VALUES (1, 2, NULL), (2, NULL, NULL);
        INSERT INTO qa_plan_executions VALUES ('replacement', 'active', NULL, NULL);
        """
    )
    conn.execute(
        "INSERT INTO qa_runs VALUES (1,1,'2026-01-01',?)",
        (json.dumps({"evidence": {"test_machine": FIRST}}),),
    )
    conn.commit()
    case = {
        "project": "yoke",
        "requirement_id": 2,
        "runner_id": "host_control",
        "method_config": {"os": "windows"},
        "starting_state": "baseline",
    }
    execution = {"id": "replacement", "roster": [case]}
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_plan_protocol.plan_case_contract_arguments",
        lambda *args, **kwargs: {
            "operation": "verify",
            "checks": VERIFICATION_CHECKS,
            "baselines": HOST_BASELINES,
        },
    )

    result = begin_case_host_contract(
        conn, execution, case, ordinal=0, test_machine=pin,
        actor_id=None, session_id="second",
    )

    assert result.settings["resource_name"] == SECOND
    assert execution["test_machine_lease_id"] == result.lease_id
