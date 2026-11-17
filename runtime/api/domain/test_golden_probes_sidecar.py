"""Golden capture proves its probes sidecar; reset names why probes are unusable."""

from __future__ import annotations

import base64
import hashlib
import json
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness import golden_harness_clis, ssh_linux_baseline
from yoke_harness.ssh_linux_reset_preconditions import reset_preflight
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_harness.standard_baseline_probes import capture_probes_document

REAL_RUN = subprocess.run


class WindowsLab(SshWindowsHostOperations):
    """The WSL host operations, with Windows OpenSSH replaced by local Python."""

    os = "wsl"
    secret_values = ()

    def __init__(self) -> None:
        pass


def _wsl_transport(monkeypatch, *, stdin_limit: int | None = None) -> None:
    """Decode the real WSL framing and run the Linux command locally.

    ``stdin_limit`` truncates the upload stream after the framed command line,
    as a lossy Windows OpenSSH -> PowerShell -> wsl.exe pipe would.
    """
    monkeypatch.setattr(
        SshTestMachineTransport,
        "_ssh_argv",
        lambda self, command: ["ssh", "windows-lab", command],
    )

    def run(argv, *, input, **kwargs):
        command_line, _, stdin = input.partition("\n")
        command = shlex.split(base64.b64decode(command_line).decode("utf-8"))
        assert command[0] == "/usr/bin/python3"
        if stdin_limit is not None:
            stdin = stdin[:stdin_limit]
        return REAL_RUN(
            [sys.executable, *command[1:]],
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture
def capture_stubs(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        ssh_linux_baseline, "prove_linux_probes", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(
        ssh_linux_baseline, "archive_operation", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(
        golden_harness_clis,
        "record_golden_harness_clis",
        lambda *a: recorded.append(a) or HostActionResult(True, {}),
    )
    return recorded


def _default_document() -> str:
    document, refusal = capture_probes_document("wsl", None)
    assert refusal is None and document is not None
    return document


def test_wsl_transport_truncating_the_upload_refuses_capture_before_registration(
    monkeypatch, tmp_path, capture_stubs
):
    document = _default_document()
    assert len(base64.b64encode(document.encode())) > 65536
    _wsl_transport(monkeypatch, stdin_limit=65536)
    golden = str(tmp_path / "golden")

    result = ssh_linux_baseline.capture_linux_golden(WindowsLab(), golden, None)

    assert not result.ok and result.error_code == "golden_probes_write_failed"
    assert result.evidence["sent_bytes"] == len(document.encode())
    assert "upload decoded 49152 of" in result.evidence["write_error"]
    assert not (tmp_path / "golden.probes").exists()
    assert not capture_stubs, "harness CLIs recorded after a failed probes write"


def test_upload_that_lands_short_without_failing_is_unverified(tmp_path, capture_stubs):
    files = {}
    control = SimpleNamespace(
        os="wsl",
        upload_remote_text=lambda path, text: files.__setitem__(path, text[:1000]),
        read_remote_text=files.get,
    )
    document = _default_document()

    result = ssh_linux_baseline.capture_linux_golden(control, "/srv/golden", None)

    assert not result.ok and result.error_code == "golden_probes_write_unverified"
    evidence = result.evidence
    assert evidence["sent_bytes"] == len(document.encode())
    assert evidence["read_bytes"] == 1000
    assert evidence["read_sha256"] != evidence["sent_sha256"]
    assert "/srv/golden.probes.sha256" not in files
    assert not capture_stubs


def test_wsl_capture_seals_verified_probes_and_digest_that_reset_accepts(
    monkeypatch, tmp_path, capture_stubs
):
    _wsl_transport(monkeypatch)
    lab = WindowsLab()
    golden = str(tmp_path / "golden")
    document = _default_document()

    result = ssh_linux_baseline.capture_linux_golden(lab, golden, None)

    assert result.ok, result.evidence
    digest = hashlib.sha256(document.encode()).hexdigest()
    assert (tmp_path / "golden.probes").read_text() == document
    assert (tmp_path / "golden.probes.sha256").read_text() == digest
    assert result.evidence["probes_sha256"] == digest
    assert capture_stubs
    preflight = reset_preflight(lab, golden)
    assert preflight.ok and preflight.evidence["sealed_probe_count"] > 0


def test_missing_probes_are_unavailable_with_their_path(monkeypatch, tmp_path):
    _wsl_transport(monkeypatch)
    golden = str(tmp_path / "golden")

    result = reset_preflight(WindowsLab(), golden)

    assert not result.ok and result.error_code == "baseline_probes_unavailable"
    assert result.evidence["probes_path"] == golden + ".probes"
    assert "missing or empty" in result.evidence["recovery"]


def test_corrupt_probes_name_exception_size_and_digests(monkeypatch, tmp_path):
    _wsl_transport(monkeypatch)
    golden = tmp_path / "golden"
    corrupt = '{"probes": [{"name": "CLI'
    (tmp_path / "golden.probes").write_text(corrupt)
    expected = hashlib.sha256(b"sealed").hexdigest()
    (tmp_path / "golden.probes.sha256").write_text(expected)

    result = reset_preflight(WindowsLab(), str(golden))

    assert not result.ok and result.error_code == "baseline_probes_invalid"
    evidence = result.evidence
    assert evidence["exception_type"] == "JSONDecodeError"
    assert "not valid JSON" in evidence["exception_message"]
    assert "char" in evidence["exception_message"]
    assert evidence["bytes"] == len(corrupt)
    assert evidence["sha256"] == hashlib.sha256(corrupt.encode()).hexdigest()
    assert evidence["expected_sha256"] == expected
    assert "CLI" not in json.dumps(
        {k: v for k, v in evidence.items() if k != "recovery"}
    )
