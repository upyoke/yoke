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
from yoke_core.domain.machine_qa_method_contracts import (
    MACHINE_METHODS,
    MachineQaExecutionError,
    machine_method_definition,
    validate_machine_method_config,
)
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS
from yoke_core.domain.qa_catalog_schema import seed_builtin_qa_methods
from yoke_core.domain.machine_qa_capability import (
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_harness.ssh_mac_preserved_state import PRESERVED_HOME_ENTRIES


def test_builtins_preserve_serial_machine_contracts_and_replace_pack_source() -> None:
    methods = [
        m
        for m in BUILTIN_QA_METHODS
        if "test-machine" in m["required_capability_kinds"]
    ]
    assert {m["id"] for m in methods} == {*MACHINE_METHODS, "exploratory-mission"}
    assert MACHINE_METHODS == {
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
    }
    conn = make_conn()
    seed_builtin_qa_methods(conn)
    conn.execute(
        "UPDATE qa_methods SET source_kind='pack', source_ref='machine-qa' "
        "WHERE id='terminal-check'"
    )
    seed_builtin_qa_methods(conn)
    for method in methods:
        row = conn.execute(
            "SELECT source_kind,source_ref,concurrency_mode,required_capability_kinds,"
            "runner_id,verdict_path,config_contract_id,proof_kind FROM qa_methods WHERE id=?",
            (method["id"],),
        ).fetchone()
        assert tuple(row[:3]) == ("built_in", None, "serial")
        expected_kinds = (
            ["browser-control", "test-machine"]
            if method["id"] == "exploratory-mission"
            else ["test-machine"]
        )
        assert json.loads(row[3]) == expected_kinds
        assert tuple(row[4:]) == tuple(
            method[k]
            for k in ("runner_id", "verdict_path", "config_contract_id", "proof_kind")
        )
    assert (
        conn.execute(
            "SELECT concurrency_mode FROM qa_methods WHERE id='command'"
        ).fetchone()[0]
        == "parallel"
    )


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
            "os": "macos",
            "operating_notes": "Do not interrupt an active lease.",
        },
        base_settings=None,
    )
    assert result["verification_status"] == "configured_unverified"
    seed_builtin_qa_methods(conn)
    detail = read_test_machine_detail(conn, project="yoke")
    assert detail["features"] == [
        "Terminal.app",
        "PTY",
        "screenshots",
        "post-install shell",
    ]
    assert detail["host_baselines"] == ["fresh-host", "shell-preconfigured"]
    assert {row["key"] for row in detail["secrets"]} == {
        *TEST_MACHINE_SECRET_KEYS,
        "desktop_password",
    }
    desktop_secret = next(
        row for row in detail["secrets"] if row["key"] == "desktop_password"
    )
    assert desktop_secret["cap_type"] == "test-machine:mac-mini-lab"
    assert is_machine_local_capability_secret(
        desktop_secret["cap_type"], desktop_secret["key"]
    )
    assert all(row["stored"] is None for row in detail["secrets"])
    assert {row["scope"] for row in detail["secrets"]} == {"executing_machine"}
    assert all(
        is_machine_local_capability_secret(TEST_MACHINE_CAPABILITY, key)
        for key in TEST_MACHINE_SECRET_KEYS
    )
    assert {row["id"] for row in detail["methods"]} == {
        "exploratory-mission",
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
            "os": "macos",
            "operating_notes": "Do not interrupt an active lease.",
        },
        base_settings=None,
    )
    seed_builtin_qa_methods(conn)
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            project_sequence INTEGER,
            title TEXT NOT NULL
        );
        INSERT INTO items(id,project_id,project_sequence,title)
        VALUES(41,1,2001,'Prove the installer campaign');
        INSERT INTO work_claims(
            id,session_id,target_kind,scope,claimed_at,released_at
        ) VALUES(8,'session-machine','item','{"item_id":41}',
                 '2026-07-26T15:55:00Z',NULL);
        INSERT INTO harness_sessions(session_id,actor_id)
        VALUES('session-machine',2);
        INSERT INTO work_claims(
            id,session_id,target_kind,scope,claimed_at,last_heartbeat,
            released_at
        ) VALUES(
            9,'session-machine','qa_admission','{"test_machine":"mac-mini-lab"}',
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
    # The Yoke managed block is gone with everything else Yoke wrote, but the
    # user's own tool directory stays on their PATH: a machine stripped back to
    # bare is not a fresh host, it is a machine no real user has.
    assert "old" not in control.files["/Users/tester/.zprofile"]
    assert ".local/bin" in control.files["/Users/tester/.zprofile"]
    assert "YOKE MANAGED PATH" not in control.files["/Users/tester/.zprofile"]
    assert fresh.evidence["baseline_state"]["preserved_entries"] == list(
        PRESERVED_HOME_ENTRIES
    )
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


@pytest.mark.parametrize(
    "method_id", ["command", "command-ci", "browser-check", "browser-inspection"]
)
def test_machine_method_reader_refuses_other_builtin_methods(method_id):
    with pytest.raises(MachineQaExecutionError, match="unknown Machine QA method"):
        machine_method_definition(method_id)
