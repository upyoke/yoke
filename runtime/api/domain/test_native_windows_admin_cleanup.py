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
    monkeypatch.setattr(admin, "upload_received", lambda *args: True)
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
def test_second_chunk_timeout_retains_safe_phase_and_cleanup(monkeypatch, cleanup_fails):
    import base64
    import hashlib

    clock = [0.0]
    calls = []
    original = subprocess.TimeoutExpired(["private-encoded-argv"], 28)
    cleanup_error = OSError("private cleanup detail")
    monkeypatch.setattr(admin.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if len(calls) == 1:
            data = base64.b64decode(kwargs["input"].split(":", 1)[1])
            clock[0] = 2.0
            return subprocess.CompletedProcess(argv, 0, f"YOKE_UPLOAD:2048:{hashlib.sha256(data).hexdigest()}", "")
        if len(calls) == 2:
            clock[0] = 30.0
            raise original
        clock[0] = 31.0
        if cleanup_fails == "oserror":
            raise cleanup_error
        if cleanup_fails == "nonzero":
            return subprocess.CompletedProcess(argv, 7, "private output", "private cleanup detail")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(admin.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    with pytest.raises(admin.AdminScriptError) as error:
        provision.admin_script("key", "host", "admin", "x" * 2130, input_text="private password")

    assert error.value.__cause__ is original
    diagnostic = error.value.diagnostics
    assert diagnostic["total_bytes"] == 2133
    assert diagnostic["total_chunks"] == 2
    assert diagnostic["last_verified_offset"] == 2048
    assert diagnostic["chunks"][1] == {
        "index": 2, "offset": 2048, "bytes": 85, "elapsed_seconds": 2.0,
        "remaining_seconds": 28.0, "duration_seconds": 28.0, "outcome": "TimeoutExpired",
    }
    assert diagnostic["upload_elapsed_seconds"] == 30.0
    assert diagnostic["cleanup_duration_seconds"] == 1.0
    assert calls[0][1]["timeout"] == 30
    assert calls[1][1]["timeout"] == 28
    assert calls[2][1]["timeout"] == 30
    assert not any(" -File " in argv[-1] for argv, _ in calls)
    assert diagnostic["owned_path"] in str(error.value)
    assert "private-encoded-argv" not in str(error.value)
    assert "private password" not in str(error.value)
    assert "private cleanup detail" not in str(error.value)
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
