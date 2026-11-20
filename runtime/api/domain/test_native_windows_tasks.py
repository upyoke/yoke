"""Safe task failures survive the Machine QA boundary."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError, host_control_failure
from yoke_harness.native_windows.journal import journal_operation
from yoke_harness.native_windows.tasks import require_task_result

pytestmark = pytest.mark.windows


def test_scheduler_failure_keeps_phase_exit_and_redacted_diagnostics():
    control = SimpleNamespace(secret_values=("private-secret",))
    result = subprocess.CompletedProcess([], 1, "", "Access denied private-secret")
    with pytest.raises(HostControlLocalError) as error:
        require_task_result(control, result, phase="journal_task_start")
    code, detail, recovery = host_control_failure(error.value, phase="screenshot_execution")
    assert code == "native_windows_task_failed"
    assert "phase=journal_task_start" in detail
    assert "exit_code=1" in detail
    assert "Access denied [REDACTED]" in detail
    assert "private-secret" not in detail
    assert "standard-user privileges" in recovery


def test_journal_start_failure_does_not_poll_or_misdiagnose_provisioning():
    uploaded = []
    control = SimpleNamespace(
        qa_lease_id="lease", secret_values=(),
        upload_remote_text=lambda *args: uploaded.append(args),
        _run=lambda *a, **kw: subprocess.CompletedProcess([], 1, "", "Scheduler RPC failed"),
        read_remote_text=lambda *a: pytest.fail("must not poll after task start failed"),
    )
    with pytest.raises(HostControlLocalError) as error:
        journal_operation(control, "restore")
    assert error.value.code == "native_windows_task_failed"
    assert error.value.phase == "journal_task_start"
    assert "Scheduler RPC failed" in str(error.value)
    assert len(uploaded) == 1


def test_offset_timeout_preserves_bound_and_carries_phase_and_target_evidence(monkeypatch, tmp_path):
    from runtime.api.domain import native_windows_fixture_upload as fixture
    target = tmp_path / "partial.bin"
    target.write_bytes(b"partial")
    monkeypatch.setattr(fixture.shutil, "which", lambda name: "powershell.exe")
    def timeout(argv, **kwargs):
        assert kwargs["timeout"] == 20
        raise subprocess.TimeoutExpired(argv, 20, output=b"", stderr=b"YOKE_CHUNK_PHASE:written")
    monkeypatch.setattr(fixture.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired) as error:
        fixture.chunk_probe(target, b"payload", 0)
    note = error.value.__notes__[0]
    assert "YOKE_CHUNK_PHASE:written" in note
    assert '"target_length": 7' in note
    assert '"target_sha256"' in note


def test_journal_program_uses_one_multiset_identity_and_rechecks_uninstall():
    from yoke_harness.native_windows.journal import PROGRAM

    tool_key = PROGRAM.split("function Tool-Key", 1)[1].split("function Json-Key", 1)[0]
    assert all(field in tool_key for field in (".Name", ".Version", ".ProviderName"))
    assert "$counts[$identity]++" in PROGRAM
    assert "$counts[$identity]--" in PROGRAM
    assert 'Restore-Tools @($state.tools) @(Tools) $attempts' in PROGRAM
    assert PROGRAM.count('${function:Tool-Key}') == 3
    uninstall = PROGRAM.split("| Uninstall-Package", 1)[1].split("catch", 1)[0]
    assert "Where-Object {(Tool-Key $_) -ceq $identity}" in uninstall
    assert "'ineffective'" in uninstall
    assert "windows_tool_uninstall_ineffective" in PROGRAM


def test_failed_restore_details_reach_refusal_and_fixture_cleanup():
    import json
    from subprocess import CompletedProcess

    from yoke_core.domain.machine_qa_fixture_lifecycle import _operation_outcomes
    from yoke_core.domain.native_windows_fixture import NativeWindowsFixture

    request = {}
    saved = {"Name": "Example", "Version": "1.0", "ProviderName": "msi"}
    current = saved | {"ProviderName": "Programs"}
    duplicate = current | {"Name": "private-token"}
    change = {
        "tools": {
            "saved_only": [saved],
            "current_only": [current, current, duplicate],
        }
    }
    attempts = [
        {"action": "uninstall", "status": "ineffective", "exit_code": None, "tool": current},
        {"action": "reinstall", "status": "failed", "exit_code": 1603, "tool": saved},
    ]
    control = SimpleNamespace(
        qa_lease_id="lease",
        secret_values=("private-token",),
        upload_remote_text=lambda path, value: request.update(json.loads(value)),
        _run=lambda command: CompletedProcess([], 0, "", ""),
        read_remote_text=lambda path: json.dumps(
            request | {
                "ok": False,
                "reason": "windows_tool_uninstall_ineffective: the package remains installed",
                "recovery": "Repair as Administrator and retry",
                "differences": change,
                "attempts": attempts,
            }
        ),
    )
    with pytest.raises(HostControlLocalError) as exc:
        journal_operation(control, "restore")
    assert "windows_tool_uninstall_ineffective" in str(exc.value)
    assert 'tools.saved_only: {"Name": "Example"' in str(exc.value)
    assert sum('tools.current_only:' in line for line in exc.value.diagnostics) == 3
    assert '"ProviderName": "msi"' in str(exc.value)
    assert '"ProviderName": "Programs"' in str(exc.value)
    assert '"status": "ineffective"' in str(exc.value)
    assert '"exit_code": 1603' in str(exc.value)
    assert "private-token" not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)

    control.journal_settings = lambda action: journal_operation(control, action)
    fixture = NativeWindowsFixture(control)
    fixture.journal_captured = True
    outcome = _operation_outcomes(fixture.close(), control.secret_values)[0]
    assert outcome["outcome"] == "failed"
    assert outcome["diagnostics"] == list(exc.value.diagnostics)
