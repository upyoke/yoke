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
from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    GOLDEN_BASELINE_PATH,
    closed_reset_stdout,
)


@pytest.fixture
def lab():
    config = {
        "machine_id": str(uuid4()),
        "active_env": "lab-org",
        "connections": {"lab-org": {
            "transport": "https",
            "api_url": "https://example.test/api/orgs/lab-org",
            "credential_source": {"kind": "token_file", "path": "/home/lab/token"},
        }},
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


@pytest.mark.parametrize(
    ("connections", "reason"),
    [({}, "identity_connection_missing"), ({"lab-org": {}}, "identity_connection_invalid")],
)
def test_identity_without_valid_owning_connection_skips_retirement(lab, connections, reason):
    lab.config["connections"] = connections
    lab.run_command = lambda *args, **kwargs: pytest.fail("used an ambient connection")

    result = retire_reset_identity(lab)

    assert not result.ok
    evidence = result.evidence["machine_retirement"]
    assert evidence["outcome"] == "skipped"
    assert evidence["reason"] == reason


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
def test_invalid_identity_skips_retirement(lab, document):
    lab.read_remote_text = lambda _: document
    lab.run_command = lambda *args, **kwargs: pytest.fail("invalid identity was used")

    result = retire_reset_identity(lab)

    assert not result.ok
    assert result.evidence["machine_retirement"]["outcome"] == "skipped"
    assert result.evidence["machine_retirement"]["reason"] == "identity_file_invalid"


@pytest.mark.parametrize("retirement_outcome", ["skipped", "failed", "retired"])
@pytest.mark.parametrize("restore_succeeds", [False, True])
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
def test_restore_outcome_is_independent_of_lab_identity_retirement(
    lab, module, reset: Callable, wipe_operation, retirement_outcome, restore_succeeds, monkeypatch
):
    events = []

    if retirement_outcome == "skipped":
        lab.config["connections"] = {}

    def run(argv, **kwargs):
        events.append("retire")
        return CompletedProcess(argv, 0 if retirement_outcome == "retired" else 1, "{}", "")

    def wipe(*args):
        events.append("wipe")
        return HostActionResult(
            restore_succeeds, {"restore": restore_succeeds},
            None if restore_succeeds else "restore_failed",
        )

    lab.run_command = run
    monkeypatch.setattr(module, wipe_operation, wipe)
    if module is ssh_linux_host_operations:
        monkeypatch.setattr(module, "probe_reset_tools", lambda _: {})
    else:
        monkeypatch.setattr(module, "probe_console", lambda *_, **__: HostActionResult(True, {}))
        lab._run = lambda script: CompletedProcess([script], 0, "", "")

    result = reset(lab)

    assert result.ok == restore_succeeds
    assert result.error_code == (None if restore_succeeds else "restore_failed")
    assert result.evidence["restore"] == restore_succeeds
    assert events == (["wipe"] if retirement_outcome == "skipped" else ["retire", "wipe"])
    evidence = result.evidence["machine_retirement"]
    assert evidence["machine_id"] == lab.config["machine_id"]
    assert evidence["outcome"] == retirement_outcome
    if retirement_outcome == "failed":
        assert evidence["reason"] == "retire_command_failed"
    elif retirement_outcome == "skipped":
        assert evidence["reason"] == "identity_connection_missing"


@pytest.mark.parametrize("restore_succeeds", [False, True])
def test_macos_records_retirement_failure_and_continues_restore(lab, restore_succeeds):
    lab.run_command = lambda argv, **_: CompletedProcess(argv, 1, "{}", "")
    transport = FakeResetTransport(
        closed_reset_stdout() if restore_succeeds else "",
        reset_returncode=0 if restore_succeeds else 1,
    )
    result = execute_full_test_machine_reset(
        home="/Users/lab",
        golden_baseline_path=GOLDEN_BASELINE_PATH,
        before_restore=lambda: retire_reset_identity(lab),
        run_remote=transport.run,
        upload_text=transport.upload,
    )

    assert result.ok == restore_succeeds
    assert result.error_code == (None if restore_succeeds else "test_mac_reset_failed")
    assert transport.uploads
    evidence = result.evidence["machine_retirement"]
    assert evidence["machine_id"] == lab.config["machine_id"]
    assert evidence["outcome"] == "failed"
    assert evidence["reason"] == "retire_command_failed"
