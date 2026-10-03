"""Reset absence proof distinguishes startup noise, executables and failed probes."""

from __future__ import annotations

import re
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_tool_resolution import probe_tool_resolution
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_harness.test_machine_types import HostActionResult


def _response(command, *, code="1", path="", exit_code=0, noise="", stderr=""):
    marker = re.search(r"YOKE_TOOL_PROBE_[a-f0-9]+", command)[0]
    return subprocess.CompletedProcess(
        command, exit_code, f"{noise}\n{marker}\t{code}\t{path}\n", stderr
    )


@pytest.mark.parametrize("surface", ["login", "ssh"])
def test_startup_stdout_is_not_tool_presence(surface):
    control = SimpleNamespace(
        shell="/bin/bash",
        secret_values=(),
        _run=lambda cmd, **kw: _response(cmd, noise="Welcome to WSL; /unrelated/path"),
    )
    evidence = probe_tool_resolution(control, surface, "yoke")
    assert evidence["state"] == "absent"
    assert evidence["resolved_path"] is None
    assert evidence["exit_code"] == 0
    assert evidence["resolution_exit_code"] == 1
    assert "Welcome to WSL" in evidence["stdout"]


def test_probe_script_resolves_each_real_executable(tmp_path):
    tool = tmp_path / "yoke"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o700)
    calls = []

    def run(command, **kwargs):
        argv = shlex.split(command)
        calls.append(argv)
        # Execute the exact probe body without loading this workstation's profiles.
        return subprocess.run(
            ["/bin/bash", "-c", argv[-1]],
            env={"PATH": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=kwargs["timeout"],
        )

    control = SimpleNamespace(shell="/bin/bash", secret_values=(), _run=run)
    present = probe_tool_resolution(control, "login", "yoke")
    absent = probe_tool_resolution(control, "ssh", "uv")
    assert present["state"] == "present"
    assert present["resolved_path"] == str(tool)
    assert absent["state"] == "absent"
    assert calls[0][1] == "-lic"
    assert calls[1][1] == "-c"


@pytest.mark.parametrize("exit_code", [2, 124, 255])
def test_shell_errors_and_transport_timeout_never_prove_absence(exit_code):
    control = SimpleNamespace(
        shell="/bin/bash",
        secret_values=("private-value",),
        _run=lambda cmd, **kw: _response(
            cmd, exit_code=exit_code, noise="private-value", stderr="private-value"
        ),
    )
    evidence = probe_tool_resolution(control, "login", "uvx")
    assert evidence["state"] == "probe-failed"
    assert evidence["exit_code"] == exit_code
    assert evidence["failure_reason"] == "shell_or_transport_failed"
    assert "private-value" not in str(evidence)


@pytest.mark.parametrize(
    "stdout", ["startup noise only", "duplicate", "invalid-exit", "function"]
)
def test_incomplete_or_non_path_resolution_is_probe_failure(stdout):
    def run(command, **kwargs):
        result = _response(command)
        if stdout == "duplicate":
            result.stdout *= 2
        elif stdout == "invalid-exit":
            result = _response(command, code="invalid")
        elif stdout == "function":
            result = _response(command, code="0", path="yoke is a function")
        else:
            result.stdout = stdout
        return result

    evidence = probe_tool_resolution(
        SimpleNamespace(shell="/bin/bash", secret_values=(), _run=run), "ssh", "yoke"
    )
    assert evidence["state"] == "probe-failed"
    assert evidence["resolved_path"] is None


@pytest.mark.parametrize("adapter", [SshLinuxHostOperations, SshWindowsHostOperations])
@pytest.mark.parametrize("outcome", ["absent", "present", "probe-failed"])
def test_reset_retains_each_surface_and_tool(monkeypatch, adapter, outcome):
    control = adapter.__new__(adapter)
    control.golden_baseline_path = "/sealed/home"
    control.shell = "/bin/bash"
    control.secret_values = ("private-value",)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "command -v uv)" in command and "-lic" in command:
            if outcome == "present":
                return _response(command, code="0", path="/opt/bin/uv")
            if outcome == "probe-failed":
                return subprocess.CompletedProcess(command, 124, "", "timed out")
        return _response(command, noise="WSL startup private-value")

    control._run = run
    monkeypatch.setattr(
        "yoke_harness.ssh_linux_host_operations.archive_operation",
        lambda *args: HostActionResult(True, {"required_paths_absent": True}),
    )
    result = control.reset_installer_test_host()
    assert len(calls) == 6
    assert result.ok is (outcome == "absent")
    assert (
        result.error_code
        == {
            "absent": None,
            "present": "reset_absence_not_proved",
            "probe-failed": "reset_tool_probe_failed",
        }[outcome]
    )
    assert result.evidence["required_paths_absent"]
    assert result.evidence["path_state"]["launcher_present"] is False
    assert (
        result.evidence["path_state"]["yoke_tools_resolve"]
        is {
            "absent": False,
            "present": True,
            "probe-failed": None,
        }[outcome]
    )
    observed = result.evidence["tool_resolution"]
    assert set(observed) == {"login", "ssh"}
    assert all(set(surface) == {"yoke", "uv", "uvx"} for surface in observed.values())
    assert "private-value" not in str(result.evidence)
    if not result.ok:
        assert "tool_resolution" in result.evidence["recovery"]
