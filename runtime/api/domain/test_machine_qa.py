from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.config import path_doctor
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
    is_machine_local_capability_secret,
)
from yoke_core.domain.host_baseline_operations import run_host_baseline
from yoke_core.domain.host_control_executor import (
    TestMachineMaterial as MachineMaterial,
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_execution import MachineQaLease
from yoke_core.domain.machine_qa_execution import (
    verify_test_machine as verify_machine,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_core.domain.machine_qa_pack import (
    load_machine_qa_methods,
    sync_machine_qa_pack_methods,
)
from yoke_core.domain.coordination_leases import Lease
from yoke_core.domain.test_machine_capability import (
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
)
from yoke_core.domain.capability_machine_secrets import (
    store_machine_capability_secret,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn


def test_pack_owns_all_three_serial_host_control_method_definitions() -> None:
    version, methods = load_machine_qa_methods()
    assert version == "1.0.1"
    assert {row["id"] for row in methods} == {
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
    }
    assert {row["executor_id"] for row in methods} == {"host_control"}
    assert {row["required_capability_kind"] for row in methods} == {"test-machine"}
    assert {row["concurrency_mode"] for row in methods} == {"serial"}
    assert {row["id"]: row["description"] for row in methods} == {
        "terminal-check": (
            "Scripted PTY interaction with any terminal program; "
            "transcript + checkpoint expectations."
        ),
        "terminal-inspection": (
            "Real Terminal screenshots at checkpoints; an agent judges "
            "them against the expected outcome."
        ),
        "machine-state-check": (
            "Shell assertions on the controlled host — any provisioning "
            "or install claim."
        ),
    }

    conn = make_conn()
    sync_machine_qa_pack_methods(conn)
    rows = conn.execute(
        "SELECT id,source_kind,source_ref FROM qa_methods ORDER BY id"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("machine-state-check", "pack", "machine-qa"),
        ("terminal-check", "pack", "machine-qa"),
        ("terminal-inspection", "pack", "machine-qa"),
    ]


def test_test_machine_is_typed_and_secret_presence_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    conn = make_conn()
    result = replace_test_machine_settings(
        conn,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "Do not interrupt an active lease.",
        },
        base_settings=None,
    )
    assert result["verification_status"] == "configured_unverified"
    sync_machine_qa_pack_methods(conn)
    detail = read_test_machine_detail(conn, project="yoke")
    assert detail["features"] == [
        "Terminal.app",
        "PTY",
        "screenshots",
        "post-install shell",
    ]
    assert detail["host_baselines"] == ["fresh-host", "shell-preconfigured"]
    assert {row["key"] for row in detail["secrets"]} == TEST_MACHINE_SECRET_KEYS
    assert not any(row["stored"] for row in detail["secrets"])
    assert all(
        is_machine_local_capability_secret(TEST_MACHINE_CAPABILITY, key)
        for key in TEST_MACHINE_SECRET_KEYS
    )
    assert {row["id"] for row in detail["methods"]} == {
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
    }


def test_active_machine_lease_projects_its_owning_work_item() -> None:
    conn = make_conn()
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "Do not interrupt an active lease.",
        },
        base_settings=None,
    )
    sync_machine_qa_pack_methods(conn)
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            project_sequence INTEGER,
            title TEXT NOT NULL
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            item_id INTEGER,
            claimed_at TEXT NOT NULL,
            released_at TEXT
        );
        INSERT INTO items(id,project_id,project_sequence,title)
        VALUES(41,1,2001,'Prove the installer campaign');
        INSERT INTO work_claims(
            id,session_id,target_kind,item_id,claimed_at,released_at
        ) VALUES(8,'session-machine','item',41,'2026-07-26T15:55:00Z',NULL);
        INSERT INTO coordination_leases(
            id,project_id,lease_key,session_id,actor_id,
            acquired_at,heartbeat_at,released_at
        ) VALUES(
            9,1,'QA_HOST:mac-mini-lab','session-machine','2',
            '2026-07-26T15:58:00Z','2026-07-26T15:59:00Z',NULL
        );
        """
    )

    detail = read_test_machine_detail(conn, project="yoke")

    assert detail["active_lease"]["item"] == {
        "id": 41,
        "ref": "YOK-2001",
        "title": "Prove the installer campaign",
    }


def test_baselines_keep_full_reset_distinct_from_shell_preconfiguration() -> None:
    control = FakeHostControl()
    fresh = run_host_baseline(control, "fresh-host")
    assert fresh.ok
    assert control.full_reset_calls == 1
    assert "old" not in control.files["/Users/tester/.zprofile"]
    assert ".local/bin" not in control.files["/Users/tester/.zprofile"]
    preconfigured = run_host_baseline(control, "shell-preconfigured")
    assert preconfigured.ok
    assert preconfigured.evidence["observed_present"] == {
        "login": True,
        "ssh": True,
    }
    assert preconfigured.evidence["launcher_executable"] is True
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": control.home, "SHELL": control.shell}
    )
    assert preconfigured.evidence["path_state"] == {
        "launcher": path_state.yoke_bin,
        "launcher_present": True,
        "tool_bin_dir": path_state.tool_bin_dir,
        "login_path_present": True,
        "ssh_path_present": True,
    }
    assert preconfigured.evidence["setup_operations"] == [
        {"id": "installer.current-release-prepare", "outcome": "passed"},
        {"id": "machine.path-prepare", "outcome": "passed"},
    ]
    assert control.full_reset_calls == 2

    dirty = FakeHostControl(refuse_full_reset=True)
    failed = run_host_baseline(dirty, "fresh-host")
    assert not failed.ok
    assert failed.error_code == "test_mac_reset_failed"
    assert failed.evidence["paths"] == [
        {"path": "/Users/tester", "outcome": "reset-failed"}
    ]


def test_failed_baseline_blocks_case_and_redaction_covers_executor_evidence() -> None:
    conn = make_conn()
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,'test-machine','{}',NULL,'now')"
    )
    control = FakeHostControl(refuse_full_reset=True)
    material = MachineMaterial(
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
        },
        secrets={"ssh_private_key": "top-secret"},
    )
    execution = MachineQaLease(
        conn=conn,
        control=control,
        material=material,
        lease=Lease(
            id=4,
            project_id=1,
            lease_key="QA_HOST:mac-mini-lab",
            session_id="session-1",
            acquired_at="now",
        ),
    )
    assert not execution.reach_baseline("fresh-host").ok
    blocked = execution.execute(
        method_id="machine-state-check",
        method_config={"assertions": [{"argv": ["/usr/bin/true"]}]},
        entry_surface=None,
        required_completion=None,
    )
    assert blocked.case_outcome == "blocked_on_precondition"
    assert blocked.evidence["case_started"] is False
    assert control.case_calls == 0

    execution.baseline = None
    passed = execution.execute(
        method_id="machine-state-check",
        method_config={"assertions": [{"argv": ["/usr/bin/true"]}]},
        entry_surface=None,
        required_completion=None,
    )
    assert passed.case_outcome == "passed"
    assert passed.evidence["output"] == "credential=[REDACTED]"
    assert control.case_calls == 1


def test_terminal_contract_requires_entry_completion_and_structured_steps() -> None:
    with pytest.raises(MachineQaExecutionError, match="entry_surface"):
        validate_machine_method_config(
            "terminal-check",
            {"steps": [{"expect": "Welcome"}]},
            entry_surface=None,
            required_completion="onboard-complete",
        )
    with pytest.raises(MachineQaExecutionError, match="unknown"):
        validate_machine_method_config(
            "machine-state-check",
            {"assertions": [{"command": "test -f ~/.yoke/config.json"}]},
            entry_surface=None,
            required_completion=None,
        )
    assert validate_machine_method_config(
        "terminal-inspection",
        {
            "steps": [
                {
                    "key": "project-screen",
                    "send": "Enter",
                    "expect": "Project",
                }
            ],
            "capture_checkpoints": ["project-screen"],
        },
        entry_surface="public-installer",
        required_completion="project-screen",
    )["capture_checkpoints"] == ["project-screen"]


def test_verifier_holds_one_lease_and_returns_only_redacted_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    conn = make_conn()
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
        },
        base_settings=None,
    )
    for key in TEST_MACHINE_SECRET_KEYS:
        store_machine_capability_secret(
            "yoke",
            TEST_MACHINE_CAPABILITY,
            key,
            "top-secret" if key == "ssh_private_key" else f"value-{key}",
        )
    control = FakeHostControl()
    register_host_control_factory(lambda material: control)
    try:
        result = verify_machine(
            conn,
            project="yoke",
            session_id="session-verify",
            actor_id="2",
        )
    finally:
        clear_host_control_factory()
    assert result["status"] == "verified"
    assert "top-secret" not in json.dumps(result)
    assert "[REDACTED]" in json.dumps(result)
    active = conn.execute(
        "SELECT COUNT(*) FROM coordination_leases WHERE released_at IS NULL"
    ).fetchone()[0]
    assert active == 0
    verified_at = conn.execute(
        "SELECT verified_at FROM project_capabilities "
        "WHERE project_id=1 AND type='test-machine'"
    ).fetchone()[0]
    assert verified_at
