"""Native Windows missions run their disk, scratch and continuity steps in PowerShell.

Each call site goes through the host control's ``MissionHostOperations``; none
of them may send a POSIX path or binary to a Windows host.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.qa_continuity_fingerprint import check_continuity
from yoke_core.domain.agent_mission_preparation import prepare_mission
from yoke_core.domain.machine_qa_mission_scratch import (
    create_mission_scratch,
    mission_scratch_present,
    remove_mission_scratch,
)
from yoke_harness import host_operations
from yoke_harness.native_windows.baseline import PRESERVED_DIRECTORIES
from yoke_harness.native_windows.mission import (
    WINDOWS_MISSION_SCRATCH_DIRECTORY,
    WINDOWS_SCRATCH_ABSENT_EXIT,
    WindowsMissionOperations,
)
from yoke_harness.ssh_native_windows_host_operations import (
    SshNativeWindowsHostOperations,
)


EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"
HOME = r"C:\Users\tester"
POSIX_MARKERS = ("/usr/bin", "/bin/", "/tmp", "$HOME", "python3")


class FakeWindowsHost(WindowsMissionOperations):
    """A Windows host that answers PowerShell scripts by marker."""

    home = HOME

    def __init__(self, replies: dict[str, tuple[int, str, str]] | None = None):
        self.scripts: list[str] = []
        self.replies = replies or {}

    def _run(self, script, *, input_text=None, timeout=60, debug_log=None):
        self.scripts.append(script)
        for marker, (code, stdout, stderr) in self.replies.items():
            if marker in script:
                return subprocess.CompletedProcess([], code, stdout, stderr)
        return subprocess.CompletedProcess([], 0, "", "")

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        raise AssertionError(f"POSIX argv route used on Windows: {argv!r}")


def _assert_windows_only(host: FakeWindowsHost) -> None:
    assert host.scripts
    for script in host.scripts:
        for marker in POSIX_MARKERS:
            assert marker not in script, (marker, script)


def _scratch(host: FakeWindowsHost) -> str:
    return str(PureWindowsPath(HOME) / WINDOWS_MISSION_SCRATCH_DIRECTORY / EXECUTION_ID)


def test_scratch_lives_under_the_profile_and_survives_the_profile_reset() -> None:
    host = FakeWindowsHost()
    assert host.mission_scratch_path(EXECUTION_ID) == _scratch(host)
    assert host.mission_scratch_root == str(
        PureWindowsPath(HOME) / "AppData/Local/YokeQaMission"
    )
    assert WINDOWS_MISSION_SCRATCH_DIRECTORY in PRESERVED_DIRECTORIES


def test_scratch_create_restricts_the_acl_and_clears_the_stale_marker() -> None:
    host = FakeWindowsHost()
    assert create_mission_scratch(host, execution_id=EXECUTION_ID) == {
        "scratch_path": _scratch(host)
    }
    create, stale = host.scripts
    assert "New-Item -ItemType Directory" in create
    assert "SetAccessRuleProtection($true,$false)" in create
    assert "ReparsePoint" in create
    assert "qa-project-owner.json" in stale and "$env:USERPROFILE" in stale
    _assert_windows_only(host)


def test_scratch_create_refusal_names_the_path_and_recovery() -> None:
    host = FakeWindowsHost({"New-Item": (1, "", "Access is denied")})
    with pytest.raises(RuntimeError) as refusal:
        create_mission_scratch(host, execution_id=EXECUTION_ID)
    message = str(refusal.value)
    assert "mission_scratch_unavailable" in message
    assert _scratch(host) in message and "Access is denied" in message
    _assert_windows_only(host)


def test_scratch_remove_proves_absence() -> None:
    host = FakeWindowsHost({"exit 3": (WINDOWS_SCRATCH_ABSENT_EXIT, "", "")})
    result = remove_mission_scratch(host, execution_id=EXECUTION_ID)
    assert result["removed"] is True
    assert result["stale_owner_marker_removed"] is True
    assert any("Remove-Item -LiteralPath $p -Recurse -Force" in s for s in host.scripts)
    _assert_windows_only(host)


@pytest.mark.parametrize(
    "exit_code,present", [(0, True), (WINDOWS_SCRATCH_ABSENT_EXIT, False)]
)
def test_scratch_present_reads_the_windows_probe(exit_code, present) -> None:
    host = FakeWindowsHost({"exit 3": (exit_code, "", "")})
    assert mission_scratch_present(host, execution_id=EXECUTION_ID) is present
    _assert_windows_only(host)


def test_stale_marker_script_only_removes_an_empty_yoke_home() -> None:
    host = FakeWindowsHost()
    assert host.remove_stale_owner_marker().returncode == 0
    (script,) = host.scripts
    assert "Get-ChildItem -LiteralPath $h -Force" in script
    _assert_windows_only(host)


@pytest.mark.parametrize("free,ok", [(2 * 1024**3, True), (1024, False)])
def test_disk_preflight_reads_the_system_drive(free, ok) -> None:
    receipt = {
        "ok": ok,
        "free_bytes": free,
        "minimum_free_bytes": 1024**3,
        "drive": "C:",
        "error_code": None if ok else "test_machine_disk_space_low",
    }
    host = FakeWindowsHost({"DriveInfo": (0, json.dumps(receipt), "")})
    if ok:
        assert host.require_mission_disk_space()["free_bytes"] == free
    else:
        with pytest.raises(HostControlLocalError) as refusal:
            host.require_mission_disk_space()
        assert refusal.value.code == "test_machine_disk_space_low"
    assert "$env:SystemDrive" in host.scripts[0]
    _assert_windows_only(host)


def test_continuity_hashes_files_with_powershell() -> None:
    host = FakeWindowsHost({"Get-FileHash": (0, '{"ok":true,"failures":[]}', "")})
    config = {"continuity_fingerprint": {"~/state.json": "a" * 64}}
    assert check_continuity(host, config) == {
        "ok": True,
        "checked_files": ["~/state.json"],
    }
    assert "-Algorithm SHA256" in host.scripts[0]
    _assert_windows_only(host)


def test_continuity_refuses_when_the_check_fails() -> None:
    host = FakeWindowsHost({"Get-FileHash": (1, "", "PowerShell failed")})
    with pytest.raises(HostControlLocalError) as refusal:
        check_continuity(host, {"continuity_fingerprint": {"~/state": "a" * 64}})
    assert refusal.value.code == "continuity_lost"


def test_prepare_mission_runs_every_step_through_windows_operations() -> None:
    receipt = {"ok": True, "free_bytes": 2 * 1024**3, "minimum_free_bytes": 1}
    host = FakeWindowsHost({"DriveInfo": (0, json.dumps(receipt), "")})
    contract = SimpleNamespace(
        baselines=[],
        continues_execution_id=None,
        cases=[SimpleNamespace(host_baseline=None, method_config={})],
        plan_execution_id=EXECUTION_ID,
        lease_id=7,
        contract_digest="digest",
    )
    execution = SimpleNamespace(
        control=host,
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: pytest.fail("no baseline declared"),
    )
    payload = prepare_mission(
        contract,
        execution_factory=lambda *a, **k: execution,
        scratch_factory=create_mission_scratch,
    )
    preparation = payload["preparation"]
    assert preparation["ok"] is True, preparation
    assert preparation["scratch_path"] == _scratch(host)
    assert preparation["evidence"]["disk_preflight"]["ok"] is True
    _assert_windows_only(host)


def test_the_native_windows_operations_implement_the_mission_contract() -> None:
    for name in (
        "mission_scratch_path",
        "require_mission_disk_space",
        "create_mission_scratch_directory",
        "remove_mission_scratch_directory",
        "probe_mission_scratch",
        "remove_stale_owner_marker",
        "check_continuity_files",
    ):
        assert getattr(SshNativeWindowsHostOperations, name) is getattr(
            WindowsMissionOperations, name
        )


def test_an_os_without_operations_refuses(monkeypatch) -> None:
    monkeypatch.delitem(host_operations.HOST_OPERATIONS_BY_OS, "windows")
    contract = SimpleNamespace(settings={"os": "windows"})
    with pytest.raises(TestMachineCapabilityError, match="no operations"):
        host_operations.host_operations_for(contract)
