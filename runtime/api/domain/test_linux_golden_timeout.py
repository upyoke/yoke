"""Linux golden archive bounds and explicit recovery from client timeouts."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import ssh_linux_baseline as baseline
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport
from yoke_harness.test_machine_types import HostActionResult


DESTINATION = "/var/lib/goldens/tester"


def _control():
    control = SimpleNamespace(
        home="/home/tester", _ssh_argv=lambda command: ["ssh", command]
    )
    control._run = lambda *args, **kwargs: SshTestMachineTransport._run(
        control, *args, **kwargs
    )
    return control


@pytest.mark.parametrize("operation", ["capture", "reset"])
def test_archive_exceeding_old_bound_succeeds_and_capture_seals_probes(
    monkeypatch, operation
):
    clock = [100.0]
    monkeypatch.setattr(baseline.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        assert kwargs["timeout"] == baseline.GOLDEN_ARCHIVE_TIMEOUT_SECONDS == 1200
        duration = 312
        assert duration < kwargs["timeout"]
        clock[0] += duration
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"ok": True, "golden_baseline_path": DESTINATION}), ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *args: HostActionResult(True, {})
    )
    uploads = []
    control = _control()
    control.upload_remote_text = lambda *args: uploads.append(args)
    if operation == "capture":
        result = baseline.capture_linux_golden(control, DESTINATION, "declared probes")
        assert uploads == [
            (DESTINATION + baseline.GOLDEN_PROBES_SUFFIX, "declared probes")
        ]
    else:
        result = baseline.archive_operation(control, operation, DESTINATION)
    assert result.ok and result.evidence["golden_baseline_path"] == DESTINATION


@pytest.mark.parametrize("operation", ["capture", "reset"])
def test_timeout_names_elapsed_time_destination_and_safe_recovery(
    monkeypatch, operation
):
    clock = [100.0]
    monkeypatch.setattr(baseline.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        clock[0] += kwargs["timeout"] + 0.25
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *args: HostActionResult(True, {})
    )
    uploads = []
    control = _control()
    control.upload_remote_text = lambda *args: uploads.append(args)
    result = (
        baseline.capture_linux_golden(control, DESTINATION, "probes")
        if operation == "capture"
        else baseline.archive_operation(control, operation, DESTINATION)
    )
    assert not result.ok and result.error_code == "linux_golden_operation_timeout"
    assert result.evidence["elapsed_seconds"] == 1200.25
    assert "1200.25 seconds" in result.evidence["detail"]
    assert result.evidence["golden_baseline_path"] == DESTINATION
    assert f"targeting {DESTINATION}" in result.evidence["recovery"]
    assert "before retrying" in result.evidence["recovery"]
    if operation == "capture":
        assert f"{DESTINATION}/home.tar.gz" in result.evidence["recovery"]
        assert f"{DESTINATION}/manifest.json" in result.evidence["recovery"]
        assert "not registered" in result.evidence["recovery"]
        assert not uploads
    else:
        assert "partly restored" in result.evidence["recovery"]


def test_unavailable_ssh_executable_is_not_reported_as_timeout(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("SSH executable unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    result = baseline.archive_operation(_control(), "capture", DESTINATION)
    assert not result.ok and result.error_code == "linux_golden_operation_failed"
