"""Real macOS copier coverage and bounded failure-receipt coverage."""

from __future__ import annotations

import base64
import ctypes
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from runtime.api.domain.test_ssh_mac_golden_capture import (
    FakeCaptureTransport,
    _capture,
)
from yoke_cli.config.path_doctor import resolve_path_state_contract
from yoke_harness.ssh_mac_full_reset_contract import resolve_full_reset_path_contract
from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_COPY_STDERR_LIMIT,
    CAPTURE_COPY_STDERR_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_PHASES,
)
from yoke_harness.ssh_mac_golden_capture_receipt import (
    capture_failure_outcome,
    closed_capture_outcomes,
)
from yoke_harness.ssh_mac_golden_capture_script import render_golden_capture_script


def _run_capture(home: Path, destination: Path, tmp_path: Path):
    script = render_golden_capture_script(
        resolve_full_reset_path_contract(
            resolve_path_state_contract(
                env={"HOME": "/Users/tester", "SHELL": "/bin/zsh"}
            )
        )
    )
    # Exercise the complete copier/manifest/finish on a disposable home, without
    # accessing the real home or its privacy database. Admission has its own tests.
    boundary = 'capture_step="$capture_phase_validate_home"'
    script = script.replace(
        boundary,
        "validate_home() { return 0; }\n"
        "assert_full_disk_access() { return 0; }\n"
        "assert_home_ownership() { return 0; }\n"
        "assert_no_yoke_residue() { return 0; }\n"
        f"TMPDIR={shlex.quote(str(tmp_path))}\n" + boundary,
        1,
    )
    return subprocess.run(
        ["/bin/zsh", "-c", script, "capture", str(home), str(destination), "a" * 64],
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS tar metadata and cp")
def test_probe_created_socket_and_fifo_are_omitted_and_captured_state_restores(
    tmp_path,
):
    home = tmp_path / "home"
    nested = home / ".cursor/projects/tmp"
    nested.mkdir(parents=True)
    (home / "regular.sock").write_text("ordinary user state")
    odd_file = home / "name with\nnewline"
    odd_file.write_text("preserve names and contents")
    odd_file.chmod(0o640)
    subprocess.run(
        ["/usr/bin/xattr", "-w", "com.apple.golden-test", "metadata", str(odd_file)],
        check=True,
    )
    (home / "link").symlink_to(odd_file.name)
    os.mkfifo(nested / "worker.pipe")
    destination = tmp_path / "golden"
    # A real-request probe can leave this endpoint before copy_home starts.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket; s=socket.socket(socket.AF_UNIX); s.bind('worker.sock')",
        ],
        cwd=nested,
        check=True,
    )
    result = _run_capture(home, destination, tmp_path)

    assert result.returncode == 0, (result.stdout, result.stderr)
    receipt = closed_capture_outcomes(result.stdout)
    assert receipt is not None
    assert receipt["captured_entries"] == 4
    assert not (destination / ".cursor/projects/tmp/worker.sock").exists()
    assert not (destination / ".cursor/projects/tmp/worker.pipe").exists()
    manifest = Path(str(destination) + ".manifest").read_text()
    assert "worker.sock" not in manifest
    restored = tmp_path / "restored"
    restored.mkdir()
    for entry in destination.iterdir():
        result = subprocess.run(
            ["/bin/cp", "-Rpf", str(entry), str(restored)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0 and not result.stderr
    assert (restored / "regular.sock").read_text() == "ordinary user state"
    restored_odd = restored / odd_file.name
    assert restored_odd.read_text() == odd_file.read_text()
    assert restored_odd.stat().st_mode & 0o777 == 0o640
    metadata = subprocess.check_output(
        ["/usr/bin/xattr", "-p", "com.apple.golden-test", str(restored_odd)]
    )
    assert metadata.strip() == b"metadata"
    assert (restored / "link").readlink() == Path(odd_file.name)


@pytest.mark.skipif(
    sys.platform != "darwin" or os.geteuid() == 0,
    reason="requires macOS and an unprivileged copier",
)
def test_unreadable_file_fails_with_its_path_and_error_without_its_contents(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    unreadable = home / "unreadable"
    secret_content = "private contents must never enter evidence"
    unreadable.write_text(secret_content)
    unreadable.chmod(0)
    try:
        result = _run_capture(home, tmp_path / "golden", tmp_path)
    finally:
        unreadable.chmod(0o600)

    assert result.returncode != 0
    phase, refusal = capture_failure_outcome(result.stdout)
    assert phase == "copy_home"
    assert "unreadable" in refusal["copy_stderr"]
    assert "Permission denied" in refusal["copy_stderr"]
    assert secret_content not in refusal["copy_stderr"]
    transport = FakeCaptureTransport(
        result.stdout, capture_returncode=result.returncode
    )
    outcome = _capture(transport)
    assert outcome.error_code == "golden_capture_copy_home_failed"
    assert outcome.evidence["refusal"] == refusal


@pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS AppleDouble metadata")
def test_container_attribute_larger_than_tar_header_limit_captures_and_restores(
    tmp_path,
):
    home = tmp_path / "home"
    container = home / "Library/Containers/weather.widget"
    container.mkdir(parents=True)
    (container / "state").write_text("sandbox container state")
    attribute = "com.apple.data-container-personality"
    metadata = b"sandbox metadata" * 100_000
    # macOS Python has no os.setxattr; this fixture also exceeds argv limits.
    setxattr = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).setxattr
    setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    setxattr.restype = ctypes.c_int
    assert (
        setxattr(
            os.fsencode(container), attribute.encode(), metadata, len(metadata), 0, 0
        )
        == 0
    ), ctypes.get_errno()
    subprocess.run(
        [
            "/bin/chmod",
            "+a",
            "everyone allow readattr,readextattr,readsecurity",
            str(container),
        ],
        check=True,
    )
    expected_acl = subprocess.check_output(
        ["/bin/ls", "-lde", str(container)]
    ).splitlines()[1:]
    destination = tmp_path / "golden"

    result = _run_capture(home, destination, tmp_path)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert closed_capture_outcomes(result.stdout) is not None
    captured = destination / container.relative_to(home)
    assert (
        subprocess.check_output(
            ["/usr/bin/xattr", "-p", attribute, str(captured)]
        ).rstrip(b"\n")
        == metadata
    )
    assert not list(destination.rglob("._*"))
    restored = tmp_path / "restored"
    restored.mkdir()
    result = subprocess.run(
        ["/bin/cp", "-Rpf", str(destination / "Library"), str(restored)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0 and not result.stderr
    restored_container = restored / container.relative_to(home)
    assert (
        subprocess.check_output(
            ["/usr/bin/xattr", "-p", attribute, str(restored_container)]
        ).rstrip(b"\n")
        == metadata
    )
    assert (restored_container / "state").read_text() == "sandbox container state"
    assert (
        subprocess.check_output(
            ["/bin/ls", "-lde", str(restored_container)]
        ).splitlines()[1:]
        == expected_acl
    )


@pytest.mark.parametrize(
    "payload", [b"", b"x" * (CAPTURE_COPY_STDERR_LIMIT + 1), b"invalid"]
)
def test_copy_diagnostics_refuse_empty_oversized_or_invalid_encoding(payload):
    encoded = base64.b64encode(payload).decode() if payload != b"invalid" else "%%%"
    receipt = (
        f"{CAPTURE_FAILURE_PREFIX}{CAPTURE_PHASES['copy_home']}\n"
        f"{CAPTURE_COPY_STDERR_PREFIX}{encoded}\n"
    )
    assert capture_failure_outcome(receipt) is None


def test_copy_diagnostics_preserve_multiline_paths_at_the_byte_limit():
    stderr = b"./path with\nnewline: Permission denied\n"
    stderr += b"x" * (CAPTURE_COPY_STDERR_LIMIT - len(stderr))
    detail = CAPTURE_COPY_STDERR_PREFIX + base64.b64encode(stderr).decode()
    receipt = f"{CAPTURE_FAILURE_PREFIX}{CAPTURE_PHASES['copy_home']}\n{detail}\n"
    phase, refusal = capture_failure_outcome(receipt)
    assert phase == "copy_home"
    assert refusal["copy_stderr"] == stderr.decode()
    assert "new destination" in refusal["recovery"]
    other_phase = receipt.replace(
        CAPTURE_PHASES["copy_home"], CAPTURE_PHASES["write_manifest"]
    )
    assert capture_failure_outcome(other_phase) is None
