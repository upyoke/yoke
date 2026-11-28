"""A failed Windows reset process stop names only the cause it proved."""

import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_harness import ssh_native_windows_host_operations
from yoke_harness.native_windows import baseline
from yoke_harness.native_windows.desktop_job import RECOVERY, TIMEOUT, UNRESOLVED
from yoke_harness.native_windows.profile_process_stop_failure import PROCESS_RUNNING, STOP_FAILED

pytestmark = pytest.mark.windows

HOME = r"C:\Users\yokeqa"
GOLDEN = r"D:\goldens\fixture"
TASK = "YokeQa-" + "0" * 32
SECRET_INPUT = r"C:\Users\yokeqa\AppData\Local\YokeQa\secret-token.command.ps1"


def _desktop(code, stderr, **diagnostics):
    result = subprocess.CompletedProcess([], code, "", stderr)
    result.desktop_diagnostics = {
        "desktop_token": "0" * 32, "task": TASK,
        "files": [{"path": SECRET_INPUT, "sha256": "f" * 64, "bytes": 9}],
        **diagnostics,
    }
    return result


NO_JOB_RECEIPT = _desktop(
    124,
    f"{TIMEOUT}: {UNRESOLVED}: task {TASK} published no verifiable job receipt; recovery: {RECOVERY}",
    phase="receipt", cleanup="unverified", process_cleanup="missing desktop job receipt",
)
JOB_EMPTY = _desktop(
    124, f"{TIMEOUT}: the desktop command exceeded 60 seconds; Windows Job confirmed empty",
    phase="receipt", cleanup="verified_absent", process_cleanup="verified_empty",
)
SURVIVOR = _desktop(
    1,
    f"{PROCESS_RUNNING}: test-user processes are still running from the resettable profile, "
    r"WindowsApps or the Codex daemon package: 4242 C:\Users\yokeqa\AppData\Local\Tool\held.exe. "
    "End them from the signed-in test session, then rerun yoke test-machine reset\n"
    f"At {SECRET_INPUT}:40 char:2",
    phase="receipt", cleanup="verified_absent",
)
UNKNOWN = _desktop(1, f"Access denied while reading {SECRET_INPUT}", phase="receipt", cleanup="verified_absent")


def _reset(monkeypatch, *stops, restore=None):
    calls = {"restore": 0, "stops": list(stops)}

    def run(script, **_):
        if "Get-YokeProfileProcesses).Count" in script:
            return subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY present", "")
        calls["restore"] += 1
        return restore or subprocess.CompletedProcess([], 0, "", "")

    def desktop(control, script, *, timeout=60, hidden=False):
        return calls["stops"].pop(0)

    monkeypatch.setattr("yoke_harness.native_windows.desktop.desktop_script", desktop)
    control = SimpleNamespace(home=HOME, _run=run)
    return baseline.profile_operation(control, "reset", GOLDEN), calls


def _assert_no_raw_inputs(refused):
    text = json.dumps(refused.evidence)
    assert SECRET_INPUT not in text and "f" * 64 not in text and "files" not in text


@pytest.mark.parametrize(
    ("stop", "cause", "unresolved", "process_cleanup"),
    [
        (NO_JOB_RECEIPT, TIMEOUT, True, "missing desktop job receipt"),
        (JOB_EMPTY, TIMEOUT, False, "verified_empty"),
    ],
)
def test_desktop_timeout_keeps_its_cause_and_never_claims_a_running_process(
    monkeypatch, stop, cause, unresolved, process_cleanup
):
    refused, calls = _reset(monkeypatch, stop)

    assert not refused.ok and calls["restore"] == 0
    assert refused.error_code == cause
    assert PROCESS_RUNNING not in refused.evidence["recovery"]
    assert "observed no surviving test-user process" in refused.evidence["recovery"]
    assert TASK in refused.evidence["recovery"] and RECOVERY in refused.evidence["recovery"]
    assert refused.evidence["desktop_task"] == {
        "exit_code": 124, "task": TASK, "phase": "receipt",
        "cleanup": stop.desktop_diagnostics["cleanup"],
        "process_cleanup": process_cleanup, "cleanup_unresolved": unresolved,
    }
    assert "profile_processes_stopped" not in refused.evidence
    _assert_no_raw_inputs(refused)


def test_observed_survivor_keeps_the_positive_process_refusal(monkeypatch):
    refused, calls = _reset(monkeypatch, SURVIVOR)

    assert not refused.ok and calls["restore"] == 0
    assert refused.error_code == PROCESS_RUNNING
    assert refused.evidence["recovery"].startswith(PROCESS_RUNNING + ": ")
    assert "4242 " in refused.evidence["recovery"]
    assert refused.evidence["desktop_task"]["exit_code"] == 1
    _assert_no_raw_inputs(refused)


def test_unknown_stop_failure_is_a_generic_stop_failure_without_raw_output(monkeypatch):
    refused, calls = _reset(monkeypatch, UNKNOWN)

    assert not refused.ok and calls["restore"] == 0
    assert refused.error_code == STOP_FAILED
    assert "Access denied" not in refused.evidence["recovery"]
    assert PROCESS_RUNNING not in refused.evidence["recovery"]
    _assert_no_raw_inputs(refused)


def test_late_desktop_timeout_refuses_without_a_second_restore(monkeypatch):
    first = subprocess.CompletedProcess([], 0, 'YOKE_RESET_PROCESSES_STOPPED ["C:\\\\a.exe"]', "")
    scan = subprocess.CompletedProcess([], 1, "", PROCESS_RUNNING + ": 7 C:\\b.exe")
    refused, calls = _reset(monkeypatch, first, NO_JOB_RECEIPT, restore=scan)

    assert not refused.ok and calls["restore"] == 1
    assert refused.error_code == TIMEOUT
    assert refused.evidence["desktop_task"]["cleanup_unresolved"] is True


def test_stop_timeout_and_retirement_timeout_stay_separate(monkeypatch):
    machine_id = str(uuid4())
    config = {
        "machine_id": machine_id, "active_env": "lab-org",
        "connections": {"lab-org": {
            "transport": "https", "api_url": "https://example.test/api/orgs/lab-org",
            "credential_source": {"kind": "token_file", "path": HOME + r"\token"},
        }},
    }

    def discovery(script, **_):
        assert "Get-YokeProfileProcesses).Count" in script
        return subprocess.CompletedProcess([], 0, "YOKE_RESET_PROCESS_DISCOVERY present", "")

    lab = SimpleNamespace(
        home=HOME, golden_baseline_path=GOLDEN, _run=discovery,
        path_state=SimpleNamespace(yoke_bin=HOME + r"\.local\bin\yoke.exe"),
        read_remote_text=lambda _: json.dumps(config),
        run_command=lambda argv, **_: subprocess.CompletedProcess(argv, 124, "", "timed out"),
    )
    monkeypatch.setattr(
        "yoke_harness.native_windows.desktop.desktop_script", lambda *_, **__: NO_JOB_RECEIPT
    )

    result = ssh_native_windows_host_operations.SshNativeWindowsHostOperations.reset_installer_test_host(lab)

    assert not result.ok and result.error_code == TIMEOUT
    assert result.evidence["machine_retirement"] == {
        "outcome": "failed", "reason": "retire_command_failed", "machine_id": machine_id,
        "exit_code": 124, "recovery": result.evidence["machine_retirement"]["recovery"],
    }
    assert result.evidence["desktop_task"]["task"] == TASK
    assert TASK not in json.dumps(result.evidence["machine_retirement"])
    _assert_no_raw_inputs(result)
