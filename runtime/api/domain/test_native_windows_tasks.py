"""Safe task failures survive the Machine QA boundary."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError, host_control_failure
from yoke_harness.native_windows.tasks import require_task_result

pytestmark = pytest.mark.windows


def test_scheduler_failure_keeps_phase_exit_and_redacted_diagnostics():
    control = SimpleNamespace(secret_values=("private-secret",))
    result = subprocess.CompletedProcess([], 1, "", "Access denied private-secret")
    with pytest.raises(HostControlLocalError) as error:
        require_task_result(control, result, phase="desktop_task_start")
    code, detail, recovery = host_control_failure(error.value, phase="screenshot_execution")
    assert code == "native_windows_task_failed"
    assert "phase=desktop_task_start" in detail
    assert "exit_code=1" in detail
    assert "Access denied [REDACTED]" in detail
    assert "private-secret" not in detail
    assert "standard-user privileges" in recovery


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
