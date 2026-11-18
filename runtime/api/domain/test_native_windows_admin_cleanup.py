"""Retain remote diagnostics without treating failed staging cleanup as success."""

import subprocess

import pytest

from yoke_harness.native_windows import admin, provision


@pytest.mark.parametrize("exit_code", [0, 9])
@pytest.mark.parametrize("cleanup_failure", ["timeout", "oserror", "nonzero"])
def test_cleanup_failure_retains_completed_diagnostics(monkeypatch, exit_code, cleanup_failure):
    primary = subprocess.CompletedProcess(
        ["remote-command"], exit_code, '{"certificate":"observed"}', "primary diagnostic"
    )
    executions = []

    def run(argv, **kwargs):
        if " -File " in argv[-1]:
            executions.append(argv)
            return primary
        if "input" in kwargs:
            return subprocess.CompletedProcess(argv, 0, "upload receipt", "")
        if cleanup_failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        if cleanup_failure == "oserror":
            raise OSError("cleanup connection unavailable")
        return subprocess.CompletedProcess(argv, 7, "", "cleanup refused")

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    monkeypatch.setattr(admin, "stage_script", lambda *args, **kwargs: None)
    cause_type = {
        "timeout": subprocess.TimeoutExpired,
        "oserror": OSError,
        "nonzero": RuntimeError,
    }[cleanup_failure]
    with pytest.raises(RuntimeError, match="windows_admin_staging_cleanup_failed") as error:
        provision.admin_script("key", "host", "admin", "Read-Certificate")

    assert len(executions) == 1
    assert error.value.primary_result is primary
    assert primary.returncode == exit_code
    assert primary.stdout == '{"certificate":"observed"}'
    assert primary.stderr == "primary diagnostic"
    assert "certificate" not in str(error.value)
    assert isinstance(error.value.__cause__, cause_type)
    assert "cleanup remains unverified" in str(error.value)
    assert "restore administrator SSH connectivity" in str(error.value)
    if cleanup_failure == "nonzero":
        assert error.value.cleanup_result.returncode == 7
        assert error.value.cleanup_result.stderr == "cleanup refused"
        assert error.value.diagnostics["cleanup_exit_code"] == 7
        assert "cleanup refused" not in str(error.value)


@pytest.mark.parametrize("cleanup_fails", [False, "oserror", "nonzero"])
def test_staging_timeout_retains_safe_phase_and_cleanup(monkeypatch, cleanup_fails):
    clock = [0.0]
    original = subprocess.TimeoutExpired(["private-encoded-argv"], 65)
    cleanup_error = OSError("private cleanup detail")
    monkeypatch.setattr(admin.time, "monotonic", lambda: clock[0])

    def stage(ssh, payload, root, diagnostic, *, deadline):
        assert deadline == 90
        assert payload == ("x" * 2130).encode("utf-8-sig")
        diagnostic["remote_directory_owned"] = True
        diagnostic["steps"].append({"phase": "sftp", "outcome": "TimeoutExpired"})
        clock[0] = 90.0
        raise original

    def run(argv, **kwargs):
        assert " -File " not in argv[-1]
        assert kwargs["timeout"] == 30
        clock[0] = 91.0
        if cleanup_fails == "oserror":
            raise cleanup_error
        if cleanup_fails == "nonzero":
            return subprocess.CompletedProcess(argv, 7, "private output", "private cleanup detail")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(admin, "stage_script", stage)
    monkeypatch.setattr(admin.subprocess, "run", run)
    with pytest.raises(admin.AdminScriptError) as error:
        provision.admin_script("key", "host", "admin", "x" * 2130, input_text="private password")

    assert error.value.__cause__ is original
    diagnostic = error.value.diagnostics
    assert diagnostic["total_bytes"] == 2133
    assert diagnostic["last_verified_offset"] == 0
    assert diagnostic["steps"] == [{"phase": "sftp", "outcome": "TimeoutExpired"}]
    assert diagnostic["upload_elapsed_seconds"] == 90.0
    assert diagnostic["cleanup_duration_seconds"] == 1.0
    assert diagnostic["owned_path"] in str(error.value)
    for private in ["private-encoded-argv", "private password", "private cleanup detail"]:
        assert private not in str(error.value)
    assert diagnostic["phase"] == "upload"
    assert diagnostic["cleanup"] == ("cleanup remains unverified" if cleanup_fails else "verified_absent")
    if cleanup_fails:
        if cleanup_fails == "oserror":
            assert error.value.staging_cleanup_cause is cleanup_error
        else:
            assert error.value.cleanup_result.returncode == 7
            assert error.value.cleanup_result.stderr == "private cleanup detail"
            assert diagnostic["cleanup_exit_code"] == 7
        assert "Owned Windows staging cleanup failed" in error.value.__notes__[0]
