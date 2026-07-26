from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn


def test_pack_owns_all_three_serial_host_control_method_definitions() -> None:
    version, methods = load_machine_qa_methods()
    assert version == "1.0.0"
    assert {row["id"] for row in methods} == {
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
    }
    assert {row["executor_id"] for row in methods} == {"host_control"}
    assert {row["required_capability_kind"] for row in methods} == {"test-machine"}
    assert {row["concurrency_mode"] for row in methods} == {"serial"}

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


def test_baselines_verify_the_path_branch_itself_and_dirty_state_fails() -> None:
    control = FakeHostControl()
    fresh = run_host_baseline(control, "fresh-host")
    assert fresh.ok
    assert fresh.evidence["observed_present"] == {
        "login": False,
        "ssh": False,
    }
    assert "old" not in control.files["/Users/tester/.zprofile"]
    assert 'export PATH="$HOME/.local/bin:$PATH"' in control.files[
        "/Users/tester/.zprofile"
    ]
    preconfigured = run_host_baseline(control, "shell-preconfigured")
    assert preconfigured.ok
    assert preconfigured.evidence["observed_present"] == {
        "login": True,
        "ssh": True,
    }

    dirty = FakeHostControl(refuse_ssh_state=True)
    failed = run_host_baseline(dirty, "fresh-host")
    assert not failed.ok
    assert failed.error_code == "baseline_verification_failed"
    assert failed.evidence["observed_present"]["ssh"] is True


def test_failed_baseline_blocks_case_and_redaction_covers_executor_evidence() -> None:
    conn = make_conn()
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,'test-machine','{}',NULL,'now')"
    )
    control = FakeHostControl(refuse_ssh_state=True)
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
            "steps": [{
                "key": "project-screen",
                "send": "Enter",
                "expect": "Project",
            }],
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


def test_ssh_adapter_uses_secret_file_reference_not_secret_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "home": "/Users/tester",
                    "shell": "/bin/zsh",
                    "xdg_bin_home": None,
                }),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    key_path = tmp_path / "ssh_private_key"
    key_path.write_text("top-secret", encoding="utf-8")
    material = MachineMaterial(
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
        },
        secrets={
            "ssh_private_key": "top-secret",
            "sudo_password": "sudo-secret",
            "screen_control_token": "screen-secret",
        },
        secret_paths={"ssh_private_key": str(key_path)},
    )
    control = SshMacHostControl(material)
    assert control.check_connection().ok
    argv_text = json.dumps([call[0] for call in calls])
    assert str(key_path) in argv_text
    assert "top-secret" not in argv_text
    assert "sudo-secret" not in argv_text
    assert "screen-secret" not in argv_text
