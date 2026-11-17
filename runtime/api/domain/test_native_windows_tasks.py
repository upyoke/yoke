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
