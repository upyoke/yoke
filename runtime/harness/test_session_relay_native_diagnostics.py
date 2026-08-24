"""Private native relay diagnostic storage tests."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from yoke_harness.session_relay_native_diagnostics import (
    NATIVE_DIAGNOSTIC_DIR_NAME,
    NATIVE_DIAGNOSTIC_MAX_BYTES,
    NATIVE_DIAGNOSTIC_MAX_FILES,
    NATIVE_DIAGNOSTIC_TTL_SECONDS,
    NativeDiagnosticError,
    cleanup_native_diagnostics,
    read_native_diagnostic,
    store_native_diagnostic,
)


def test_private_capture_is_bounded_owner_only_and_round_trips(
    tmp_path: Path,
) -> None:
    stdout = b"stdout-secret\n" * 20_000
    stderr = b"stderr-secret\n" * 20_000

    receipt = store_native_diagnostic(stdout, stderr, state_dir=tmp_path, now=1000)
    directory = tmp_path / NATIVE_DIAGNOSTIC_DIR_NAME
    capture = directory / f"{receipt.reference}.capture"
    payload = read_native_diagnostic(receipt.reference, state_dir=tmp_path, now=1001)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(capture.stat().st_mode) == 0o600
    assert capture.stat().st_uid == os.getuid()
    assert len(payload) <= NATIVE_DIAGNOSTIC_MAX_BYTES
    assert b"--- stdout ---" in payload
    assert b"--- stderr ---" in payload
    assert receipt.reference not in payload.decode(errors="ignore")
    assert receipt.expires_at == 1000 + NATIVE_DIAGNOSTIC_TTL_SECONDS


def test_reader_refuses_traversal_symlinks_wrong_owner_and_open_permissions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    directory = tmp_path / NATIVE_DIAGNOSTIC_DIR_NAME
    directory.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    symlink_ref = "nd-" + "a" * 32
    (directory / f"{symlink_ref}.capture").symlink_to(outside)

    with pytest.raises(NativeDiagnosticError, match="unavailable|regular file"):
        read_native_diagnostic(symlink_ref, state_dir=tmp_path, now=1)
    with pytest.raises(NativeDiagnosticError, match="reference is invalid"):
        read_native_diagnostic("../outside", state_dir=tmp_path, now=1)

    receipt = store_native_diagnostic(b"out", b"err", state_dir=tmp_path, now=2)
    capture = directory / f"{receipt.reference}.capture"
    capture.chmod(0o644)
    with pytest.raises(NativeDiagnosticError, match="permissions"):
        read_native_diagnostic(receipt.reference, state_dir=tmp_path, now=3)

    capture.chmod(0o600)
    real_fstat = os.fstat

    def wrong_owner(descriptor: int):
        values = list(real_fstat(descriptor))
        values[4] = os.getuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", wrong_owner)
    with pytest.raises(NativeDiagnosticError, match="different owner"):
        read_native_diagnostic(receipt.reference, state_dir=tmp_path, now=3)


def test_cleanup_enforces_ttl_and_count_without_following_unknown_entries(
    tmp_path: Path,
) -> None:
    directory = tmp_path / NATIVE_DIAGNOSTIC_DIR_NAME
    directory.mkdir(mode=0o700)
    unknown = directory / "operator-note"
    unknown.write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")
    (directory / ("nd-" + "f" * 32 + ".capture")).symlink_to(outside)

    for index in range(NATIVE_DIAGNOSTIC_MAX_FILES + 4):
        receipt = store_native_diagnostic(
            str(index).encode(),
            b"err",
            state_dir=tmp_path,
            now=1000 + index,
        )
        path = directory / f"{receipt.reference}.capture"
        os.utime(path, (1000 + index, 1000 + index))

    captures = tuple(directory.glob("*.capture"))
    regular_captures = tuple(path for path in captures if not path.is_symlink())
    assert len(regular_captures) <= NATIVE_DIAGNOSTIC_MAX_FILES
    assert unknown.read_text(encoding="utf-8") == "keep"
    assert outside.read_text(encoding="utf-8") == "keep"

    cleanup_native_diagnostics(
        tmp_path,
        now=2000 + NATIVE_DIAGNOSTIC_TTL_SECONDS,
    )
    assert not tuple(
        path for path in directory.glob("*.capture") if not path.is_symlink()
    )
    assert unknown.exists()
    assert outside.exists()


def test_reader_refuses_expired_capture(tmp_path: Path) -> None:
    receipt = store_native_diagnostic(b"out", b"err", state_dir=tmp_path, now=10)
    capture = tmp_path / NATIVE_DIAGNOSTIC_DIR_NAME / f"{receipt.reference}.capture"
    os.utime(capture, (10, 10))

    with pytest.raises(NativeDiagnosticError, match="expired"):
        read_native_diagnostic(
            receipt.reference,
            state_dir=tmp_path,
            now=10 + NATIVE_DIAGNOSTIC_TTL_SECONDS,
        )


def test_reader_refuses_capture_replaced_with_oversized_file(tmp_path: Path) -> None:
    receipt = store_native_diagnostic(b"out", b"err", state_dir=tmp_path, now=10)
    capture = tmp_path / NATIVE_DIAGNOSTIC_DIR_NAME / f"{receipt.reference}.capture"
    capture.write_bytes(b"x" * (NATIVE_DIAGNOSTIC_MAX_BYTES + 1))
    capture.chmod(0o600)

    with pytest.raises(NativeDiagnosticError, match="retention limit"):
        read_native_diagnostic(receipt.reference, state_dir=tmp_path, now=11)
