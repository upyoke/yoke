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
