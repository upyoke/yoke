"""Retain remote diagnostics without treating failed staging cleanup as success."""

import subprocess

import pytest

from yoke_harness.native_windows import provision


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
    monkeypatch.setattr(provision, "upload_received", lambda *args: True)
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
