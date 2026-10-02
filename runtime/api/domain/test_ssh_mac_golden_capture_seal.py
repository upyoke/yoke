"""Probe sealing preserves BSD chmod semantics and actionable failures."""

from __future__ import annotations

import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_ssh_mac_golden_capture import (
    DESTINATION,
    PROBES,
    FakeCaptureTransport,
    _capture,
    closed_capture_stdout,
)
from yoke_contracts.machine_qa_failures import MACHINE_QA_DIAGNOSTIC_LIMIT
from yoke_harness.ssh_mac_full_reset_contract import GOLDEN_PROBES_SUFFIX
from yoke_harness.ssh_mac_golden_capture_contract import GOLDEN_SIDECAR_MODE
from yoke_harness.ssh_mac_transport import SshMacTransport


def test_chmod_failure_retains_the_remote_status_stderr_and_recovery():
    transport = FakeCaptureTransport(closed_capture_stdout())
    transport.seal_returncode = 1

    result = _capture(transport)

    assert not result.ok
    assert result.error_code == "golden_probes_seal_failed"
    refusal = result.evidence["refusal"]
    assert refusal["reason"] == "golden_probes_chmod_failed"
    assert refusal["step"] == "chmod"
    assert refusal["exit_code"] == 1
    assert refusal["stderr"] == "seal denied"
    assert refusal["path"] == DESTINATION + GOLDEN_PROBES_SUFFIX
    assert "new destination" in refusal["recovery"]
    assert "do not register or overwrite" in refusal["recovery"]


def test_upload_failure_retains_transport_status_and_redacts_credentials():
    transport = FakeCaptureTransport(closed_capture_stdout())
    control = object.__new__(SshMacTransport)
    control.secret_values = ("private-credential",)
    control._run = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=73,
        stderr="Permission denied private-credential " + "x" * 1000,
    )
    upload = transport.upload

    def fail_sidecar_upload(path, content):
        if path.endswith(GOLDEN_PROBES_SUFFIX):
            control.upload_remote_text(path, content)
        else:
            upload(path, content)

    result = _capture(transport, upload_text=fail_sidecar_upload)

    assert not result.ok
    assert result.error_code == "golden_probes_seal_failed"
    refusal = result.evidence["refusal"]
    assert refusal["reason"] == "golden_probes_upload_failed"
    assert refusal["step"] == "upload"
    assert refusal["exit_code"] == 73
    assert refusal["error_type"] == "HostControlLocalError"
    assert "Permission denied [REDACTED]" in refusal["stderr"]
    assert len(refusal["stderr"]) <= MACHINE_QA_DIAGNOSTIC_LIMIT
    assert "private-credential" not in str(result.evidence)
    assert PROBES not in str(result.evidence)
    assert not any(
        GOLDEN_SIDECAR_MODE in shlex.split(command)
        for command, _timeout in transport.commands
    )


@pytest.mark.parametrize("step", ["upload", "chmod"])
def test_untyped_transport_exception_names_its_step_without_exposing_its_body(step):
    transport = FakeCaptureTransport(closed_capture_stdout())
    run, upload = transport.run, transport.upload

    def fail_upload(path, content):
        if step == "upload" and path.endswith(GOLDEN_PROBES_SUFFIX):
            raise RuntimeError("private exception body")
        return upload(path, content)

    def fail_chmod(command, **kwargs):
        if step == "chmod" and GOLDEN_SIDECAR_MODE in shlex.split(command):
            raise RuntimeError("private exception body")
        return run(command, **kwargs)

    result = _capture(transport, run_remote=fail_chmod, upload_text=fail_upload)

    assert not result.ok
    refusal = result.evidence["refusal"]
    assert refusal["step"] == step
    assert refusal["exit_code"] is None
    assert refusal["error_type"] == "RuntimeError"
    assert "private exception body" not in str(result.evidence)


def test_transport_fake_applies_bsd_chmod_rules_and_seals_the_uploaded_probes():
    transport = FakeCaptureTransport(closed_capture_stdout())
    run = transport.run
    modes = {}

    def bsd_chmod(command, **kwargs):
        argv = shlex.split(command)
        if argv[0] == "/bin/chmod" and GOLDEN_SIDECAR_MODE in argv:
            operands = argv[1:]
            if operands[0] == "--":
                operands = operands[1:]
            mode, *paths = operands
            for path in paths:
                if path not in transport.uploads:
                    return SimpleNamespace(
                        returncode=1, stdout="", stderr=f"chmod: {path}: No such file"
                    )
                modes[path] = mode
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run(command, **kwargs)

    result = _capture(transport, run_remote=bsd_chmod)

    assert result.ok, result.evidence
    sidecar = DESTINATION + GOLDEN_PROBES_SUFFIX
    assert transport.uploads[sidecar] == PROBES
    assert modes[sidecar] == GOLDEN_SIDECAR_MODE
    assert {row["path"]: row["outcome"] for row in result.evidence["paths"]}[
        sidecar
    ] == "sealed"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the real BSD chmod")
def test_seal_command_succeeds_with_real_macos_chmod_on_a_disposable_sidecar(tmp_path):
    transport = FakeCaptureTransport(closed_capture_stdout())
    sidecar = tmp_path / "golden.probes"
    run, upload = transport.run, transport.upload

    def upload_sidecar(path, content):
        upload(path, content)
        if path.endswith(GOLDEN_PROBES_SUFFIX):
            sidecar.write_text(content)

    def real_chmod(command, **kwargs):
        argv = shlex.split(command)
        if argv[0] == "/bin/chmod" and GOLDEN_SIDECAR_MODE in argv:
            return subprocess.run(
                [*argv[:-1], str(sidecar)], capture_output=True, text=True, timeout=5
            )
        return run(command, **kwargs)

    result = _capture(transport, run_remote=real_chmod, upload_text=upload_sidecar)

    assert result.ok, result.evidence
    assert sidecar.read_text() == PROBES
    assert sidecar.stat().st_mode & 0o777 == 0o444
