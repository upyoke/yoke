"""Native absence requires complete, correlated feature proof."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.features import feature_states, features_absent
from yoke_harness.native_windows.journal import journal_operation
from yoke_harness.ssh_native_windows_host_operations import SshNativeWindowsHostOperations

pytestmark = pytest.mark.windows
ROWS = [{"Name": "Microsoft-Windows-Subsystem-Linux", "InstallState": 2},
        {"Name": "VirtualMachinePlatform", "InstallState": 3}]


def test_both_disabled_or_absent_required():
    assert features_absent(feature_states(ROWS))
    enabled = [ROWS[0] | {"InstallState": 1}, ROWS[1]]
    assert not features_absent(feature_states(enabled))
    assert not features_absent({})


@pytest.mark.parametrize("rows", [None, [], ROWS[:1], [ROWS[0], ROWS[0]],
    [ROWS[0] | {"InstallState": "2"}, ROWS[1]],
    [ROWS[0] | {"InstallState": True}, ROWS[1]],
    [ROWS[0] | {"InstallState": 4}, ROWS[1]],
    [ROWS[0] | {"Name": []}, ROWS[1]], [{}, ROWS[1]]])
def test_missing_unknown_or_malformed_features_refuse(rows):
    with pytest.raises(HostControlLocalError) as error:
        feature_states(rows)
    assert error.value.code == "native_windows_features_unverified"


def test_failed_rebind_clears_previous_feature_proof(monkeypatch):
    control = object.__new__(SshNativeWindowsHostOperations)
    control.native_features = feature_states(ROWS)
    control._feature_lease_id = "old"
    def fail(*args):
        raise RuntimeError("recovery failed")
    monkeypatch.setattr("yoke_harness.ssh_native_windows_host_operations.journal_operation", fail)
    with pytest.raises(RuntimeError, match="recovery failed"):
        control.bind_qa_lease("new")
    assert control.native_features is None
    assert control._feature_lease_id is None
    with pytest.raises(HostControlLocalError, match="No current-lease"):
        control.check_connection()


@pytest.mark.parametrize("change", [{"lease": "old"}, {"action": "capture"}, {"ok": 1}])
def test_current_nonce_cannot_accept_foreign_lease_action_or_truthy_ok(change):
    request = {}
    control = SimpleNamespace(
        qa_lease_id="current", secret_values=(),
        upload_remote_text=lambda path, text: request.update(json.loads(text)),
        _run=lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""),
        read_remote_text=lambda path: json.dumps(request | {"ok": True} | change),
    )
    with pytest.raises(HostControlLocalError) as error:
        journal_operation(control, "restore")
    assert error.value.code == "native_windows_journal_receipt_invalid"


def test_stale_nonce_is_ignored_before_current_complete_receipt(monkeypatch):
    request = {}
    count = [0]
    def read(path):
        count[0] += 1
        return json.dumps(request | {"ok": True, "token": "stale" if count[0] == 1 else request["token"]})
    control = SimpleNamespace(
        qa_lease_id="current", upload_remote_text=lambda path, text: request.update(json.loads(text)),
        _run=lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""), read_remote_text=read,
    )
    monkeypatch.setattr("yoke_harness.native_windows.journal.time.sleep", lambda n: None)
    assert journal_operation(control, "restore")["token"] == request["token"]
    assert count[0] == 2


def _bound_control(monkeypatch, calls):
    control = object.__new__(SshNativeWindowsHostOperations)

    def journal(control, action):
        calls.append(action)
        return {"features": ROWS} if action == "restore" else {}

    monkeypatch.setattr("yoke_harness.ssh_native_windows_host_operations.journal_operation", journal)
    control.bind_qa_lease("current")
    return control


@pytest.mark.parametrize("mutations", [[], ["tools"], ["applocker", "long_paths", "certificates"]])
def test_only_declared_mutation_captures_and_restores(monkeypatch, mutations):
    from yoke_core.domain.native_windows_fixture import NativeWindowsFixture

    calls = []
    control = _bound_control(monkeypatch, calls)
    setup = [{"id": "machine.windows-settings-journal", "parameters": {"mutations": mutations}}] if mutations else []
    fixture = NativeWindowsFixture(control)
    assert fixture.execute_setup_operations(setup).ok
    assert calls == (["restore", "restore", "capture"] if mutations else ["restore"])
    assert control.native_features == feature_states(ROWS)
    assert control._feature_lease_id == "current"
    assert fixture.close().ok
    assert fixture.close().ok
    assert calls == (["restore", "restore", "capture", "restore"] if mutations else ["restore"])


@pytest.mark.parametrize("mutations", [[], ["user_path"], ["tools", "tools"], "tools"])
def test_journal_declaration_validation_precedes_remote_work(mutations):
    from yoke_core.domain.machine_qa_fixture_validation import MachineQaFixtureOperationError
    from yoke_core.domain.native_windows_fixture import NativeWindowsFixture

    fixture = NativeWindowsFixture(SimpleNamespace())
    with pytest.raises(MachineQaFixtureOperationError, match="mutations must name distinct entries"):
        fixture.execute_setup_operations([
            {"id": "machine.windows-settings-journal", "parameters": {"mutations": mutations}}
        ])
    assert fixture.close().ok


def test_failed_restore_after_capture_still_clears_the_proof(monkeypatch):
    calls = []
    control = _bound_control(monkeypatch, calls)
    control.journal_settings("capture")

    def fail(*args):
        raise RuntimeError("restore failed")

    monkeypatch.setattr("yoke_harness.ssh_native_windows_host_operations.journal_operation", fail)
    with pytest.raises(RuntimeError, match="restore failed"):
        control.journal_settings("restore")
    assert control.native_features is None
    with pytest.raises(HostControlLocalError, match="No current-lease"):
        control.check_connection()


@pytest.mark.parametrize(("free", "expected"), [
    (1024**3, True),
    (1024**3 - 1, False),
    (0, False),
])
def test_native_connection_reports_and_enforces_commit_headroom(monkeypatch, free, expected):
    control = _bound_control(monkeypatch, [])
    control.windows_facts = {"edition": "Enterprise", "build": "26200"}
    limit = 8 * 1024**3
    scripts = []

    def run(script, **kwargs):
        scripts.append(script)
        output = (
            {"commit_limit_bytes": limit, "committed_bytes": limit - free}
            if "GetPerformanceInfo" in script else {"yoke_release": "absent"}
        )
        return subprocess.CompletedProcess([], 0, json.dumps(output), "")

    control._run = run
    monkeypatch.setattr("yoke_harness.golden_harness_clis.probe_harness_cli_versions", lambda _: {})
    receipt = control.check_connection()
    assert receipt.ok is expected
    assert receipt.evidence["free_commit_bytes"] == free
    assert receipt.evidence["minimum_free_commit_bytes"] == 1024**3
    assert len(scripts) == (2 if expected else 1)
    if not expected:
        assert receipt.error_code == "native_windows_host_resources_exhausted"
        assert "enlarge the Windows page file" in receipt.evidence["recovery"]


@pytest.mark.parametrize(("code", "stdout"), [
    (1, ""),
    (0, "null"),
    (0, '{"commit_limit_bytes": 1, "committed_bytes": false}'),
])
def test_native_connection_refuses_unverified_commit_counters(monkeypatch, code, stdout):
    control = _bound_control(monkeypatch, [])
    control.secret_values = ("private-password",)
    control._run = lambda *a, **kw: subprocess.CompletedProcess([], code, stdout, "private-password")
    receipt = control.check_connection()
    assert not receipt.ok
    assert receipt.error_code == "native_windows_commit_memory_unverified"
    assert receipt.evidence["stderr"] == "[REDACTED]"
