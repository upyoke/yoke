"""Test Machine reset preserves the evidence required to retire the exact lab UUID."""

from collections.abc import Callable
import json
from pathlib import PurePosixPath, PureWindowsPath
from subprocess import CompletedProcess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness import ssh_linux_host_operations, ssh_native_windows_host_operations
from yoke_harness.ssh_mac_full_reset import execute_full_test_machine_reset
from yoke_harness.test_machine_reset_identity import retire_reset_identity


@pytest.fixture
def lab():
    config = {
        "machine_id": str(uuid4()),
        "active_env": "lab-org",
        "connections": {"lab-org": {}},
    }
    return SimpleNamespace(
        home="/home/lab",
        golden_baseline_path="/golden/lab/home",
        path_state=SimpleNamespace(yoke_bin="/home/lab/.local/bin/yoke"),
        config=config,
        read_remote_text=lambda _: json.dumps(config),
    )


@pytest.mark.parametrize("native_windows", [False, True])
def test_retirement_uses_exact_id_and_saved_environment(lab, native_windows, monkeypatch):
    if native_windows:
        lab.home = r"C:\Users\lab"
        lab.path_state.yoke_bin = r"C:\Users\lab\.local\bin\yoke.cmd"
    path_type = PureWindowsPath if native_windows else PurePosixPath
    files = []
    commands = []

    def read_text(path):
        files.append(path)
        return json.dumps(lab.config)

    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        return CompletedProcess(argv, 0, "{}", "")

    lab.read_remote_text, lab.run_command = read_text, run
    monkeypatch.setenv("YOKE_ENV", "controller-qa")

    result = retire_reset_identity(lab, native_windows=native_windows)

    assert result.ok
    assert files == [str(path_type(lab.home) / ".yoke" / "config.json")]
    argv, kwargs = commands[0]
    assert argv == [
        lab.path_state.yoke_bin, "--env", "lab-org", "machine", "retire",
        lab.config["machine_id"], "--confirm", "--json",
    ]
    assert kwargs["required_session_context"] == ("gui" if native_windows else None)
    assert result.evidence["machine_retirement"] == {
        "machine_id": lab.config["machine_id"], "outcome": "retired",
    }


def test_missing_identity_needs_no_retirement(lab):
    lab.read_remote_text = lambda _: None
    lab.run_command = lambda *args, **kwargs: pytest.fail("nothing to retire")

    assert retire_reset_identity(lab) == HostActionResult(True, {})


def test_identity_without_owning_connection_refuses_before_wipe(lab):
    lab.config["connections"] = {}
    lab.run_command = lambda *args, **kwargs: pytest.fail("used an ambient connection")

    result = retire_reset_identity(lab)

    assert not result.ok
    assert result.evidence["machine_retirement"]["reason"] == "identity_connection_missing"


@pytest.mark.parametrize(
    ("code", "expected"),
    [("machine_retired", "already_retired"), ("machine_unregistered", "already_absent")],
)
def test_retirement_retry_can_proceed_after_authoritative_confirmation(lab, code, expected):
    def run(argv, **kwargs):
        return CompletedProcess(argv, 1, json.dumps({"error": {"code": code}}), "")

    lab.run_command = run
    result = retire_reset_identity(lab)

    assert result.ok
    assert result.evidence["machine_retirement"]["outcome"] == expected


@pytest.mark.parametrize("document", ["", "[]", '{"machine_id":"not-a-uuid"}'])
def test_invalid_identity_leaves_profile_intact(lab, document):
    lab.read_remote_text = lambda _: document
    lab.run_command = lambda *args, **kwargs: pytest.fail("invalid identity was used")

    result = retire_reset_identity(lab)

    assert not result.ok
    assert result.evidence["machine_retirement"]["reason"] == "identity_file_invalid"


@pytest.mark.parametrize("retirement_succeeds", [False, True])
@pytest.mark.parametrize(
    ("module", "reset", "wipe_operation"),
    [
        (
            ssh_linux_host_operations,
            ssh_linux_host_operations.SshLinuxHostOperations.reset_installer_test_host,
            "archive_operation",
        ),
        (
            ssh_native_windows_host_operations,
            ssh_native_windows_host_operations.SshNativeWindowsHostOperations.reset_installer_test_host,
            "profile_operation",
        ),
    ],
)
def test_lab_identity_retirement_precedes_wipe(
    lab, module, reset: Callable, wipe_operation, retirement_succeeds, monkeypatch
):
    events = []

    def run(argv, **kwargs):
        events.append("retire")
        return CompletedProcess(argv, 0 if retirement_succeeds else 1, "{}", "")

    def wipe(*args):
        events.append("wipe")
        return HostActionResult(False, {"restore": "failed"}, "restore_failed")

    lab.run_command = run
    monkeypatch.setattr(module, wipe_operation, wipe)

    result = reset(lab)

    assert not result.ok
    assert events == (["retire", "wipe"] if retirement_succeeds else ["retire"])
    evidence = result.evidence["machine_retirement"]
    assert evidence["machine_id"] == lab.config["machine_id"]
    if retirement_succeeds:
        assert evidence["outcome"] == "retired"
        assert result.error_code == "restore_failed"
    else:
        assert evidence["reason"] == "retire_command_failed"
        assert "has not been wiped" in evidence["recovery"]
        assert result.error_code == "test_machine_identity_retirement_failed"


def test_macos_retirement_refusal_prevents_remote_restore():
    refused = HostActionResult(False, {"machine_retirement": {}}, "retirement_failed")
    result = execute_full_test_machine_reset(
        home="/Users/lab",
        golden_baseline_path="/private/tmp/golden/lab-home",
        before_restore=lambda: refused,
        run_remote=lambda *args, **kwargs: pytest.fail("restore ran after refusal"),
        upload_text=lambda *args: pytest.fail("restore staged after refusal"),
    )

    assert result == refused
