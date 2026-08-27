"""Machine-user-local retention for bounded native relay failure output."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import stat
import time

from yoke_contracts.session_control.evidence import (
    NATIVE_DIAGNOSTIC_REFERENCE_PATTERN,
)
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_DISCLAIMER_REFUSAL,
)
from yoke_harness.session_relay_schedule import relay_state_dir


NATIVE_DIAGNOSTIC_DIR_NAME = "native-diagnostics"
# Two independently capped 64-KiB native streams plus the human-readable envelope.
NATIVE_DIAGNOSTIC_MAX_BYTES = 132 * 1024
NATIVE_DIAGNOSTIC_MAX_FILES = 32
NATIVE_DIAGNOSTIC_TTL_SECONDS = 7 * 24 * 60 * 60
_FILE_SUFFIX = ".capture"
PERMISSION_BYPASS_UNACCEPTED = "permission_bypass_unaccepted"
_BACKGROUND_IN_USE_MARKERS = (
    b"session is already in use",
    b"conversation is already in use",
    b"already in use by another process",
    b"session is currently in use",
)


class NativeDiagnosticError(RuntimeError):
    """A private native diagnostic could not be stored or read safely."""


@dataclass(frozen=True)
class NativeDiagnosticReceipt:
    reference: str
    fingerprint_sha256: str
    expires_at: int


def classify_native_failure(stderr: bytes) -> str:
    """Map private native stderr to a small non-secret failure taxonomy."""
    lowered = bytes(stderr).lower()
    if CLAUDE_BYPASS_DISCLAIMER_REFUSAL.encode() in lowered:
        return PERMISSION_BYPASS_UNACCEPTED
    if b"no conversation found with session id" in lowered:
        return "no_conversation_found"
    if any(marker in lowered for marker in _BACKGROUND_IN_USE_MARKERS):
        return "background_session_in_use"
    return "process_exit"


def _require_private_directory(path: Path, *, create: bool) -> Path:
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise NativeDiagnosticError("diagnostic directory is unavailable") from exc
    try:
        details = path.lstat()
    except OSError as exc:
        raise NativeDiagnosticError("diagnostic directory is unavailable") from exc
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise NativeDiagnosticError("diagnostic directory is not a real directory")
    if details.st_uid != os.getuid():
        raise NativeDiagnosticError("diagnostic directory has a different owner")
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise NativeDiagnosticError(
            "diagnostic directory cannot be made private"
        ) from exc
    return path


def _diagnostic_directory(state_dir: Path | None, *, create: bool) -> Path:
    state = _require_private_directory(state_dir or relay_state_dir(), create=create)
    return _require_private_directory(
        state / NATIVE_DIAGNOSTIC_DIR_NAME,
        create=create,
    )


def _reference_path(directory: Path, reference: str) -> Path:
    if NATIVE_DIAGNOSTIC_REFERENCE_PATTERN.fullmatch(reference) is None:
        raise NativeDiagnosticError("diagnostic reference is invalid")
    return directory / f"{reference}{_FILE_SUFFIX}"


def _require_private_file(details: os.stat_result) -> None:
    if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise NativeDiagnosticError("diagnostic is not a regular file")
    if details.st_uid != os.getuid():
        raise NativeDiagnosticError("diagnostic has a different owner")
    if stat.S_IMODE(details.st_mode) != 0o600:
        raise NativeDiagnosticError("diagnostic permissions are not private")


def _retained_payload(stdout: bytes, stderr: bytes) -> bytes:
    prefix = b"YOKE NATIVE RELAY DIAGNOSTIC v1\n--- stdout ---\n"
    separator = b"\n--- stderr ---\n"
    budget = NATIVE_DIAGNOSTIC_MAX_BYTES - len(prefix) - len(separator)
    stdout_budget = budget // 2
    return (
        prefix + stdout[:stdout_budget] + separator + stderr[: budget - stdout_budget]
    )


def _known_files(directory: Path) -> list[tuple[Path, os.stat_result]]:
    retained: list[tuple[Path, os.stat_result]] = []
    try:
        children = tuple(directory.iterdir())
    except OSError:
        return retained
    for child in children:
        name = child.name
        if not name.endswith(_FILE_SUFFIX):
            continue
        reference = name[: -len(_FILE_SUFFIX)]
        if NATIVE_DIAGNOSTIC_REFERENCE_PATTERN.fullmatch(reference) is None:
            continue
        try:
            details = child.lstat()
        except OSError:
            continue
        if (
            stat.S_ISREG(details.st_mode)
            and not stat.S_ISLNK(details.st_mode)
            and details.st_uid == os.getuid()
        ):
            retained.append((child, details))
    return retained


def cleanup_native_diagnostics(
    state_dir: Path | None = None,
    *,
    now: float | None = None,
) -> None:
    """Remove expired captures and cap the retained owner-only file count."""
    directory = _diagnostic_directory(state_dir, create=True)
    current = time.time() if now is None else now
    current_files: list[tuple[Path, os.stat_result]] = []
    for path, details in _known_files(directory):
        if current - details.st_mtime >= NATIVE_DIAGNOSTIC_TTL_SECONDS:
            try:
                path.unlink()
            except OSError:
                pass
        else:
            current_files.append((path, details))
    current_files.sort(key=lambda item: item[1].st_mtime, reverse=True)
    for path, _details in current_files[NATIVE_DIAGNOSTIC_MAX_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def store_native_diagnostic(
    stdout: bytes,
    stderr: bytes,
    *,
    state_dir: Path | None = None,
    now: float | None = None,
) -> NativeDiagnosticReceipt:
    """Persist bounded private streams and return only opaque safe metadata."""
    current = time.time() if now is None else now
    directory = _diagnostic_directory(state_dir, create=True)
    cleanup_native_diagnostics(state_dir, now=current)
    payload = _retained_payload(bytes(stdout), bytes(stderr))
    for _attempt in range(4):
        reference = f"nd-{secrets.token_hex(16)}"
        path = _reference_path(directory, reference)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            continue
        except OSError as exc:
            raise NativeDiagnosticError("diagnostic could not be created") from exc
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
                raise NativeDiagnosticError("diagnostic target is unsafe")
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = -1
                stream.write(payload)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        cleanup_native_diagnostics(state_dir, now=current)
        return NativeDiagnosticReceipt(
            reference,
            hashlib.sha256(payload).hexdigest(),
            int(current) + NATIVE_DIAGNOSTIC_TTL_SECONDS,
        )
    raise NativeDiagnosticError("diagnostic reference allocation was exhausted")


def read_native_diagnostic(
    reference: str,
    *,
    state_dir: Path | None = None,
    now: float | None = None,
) -> bytes:
    """Read an unexpired capture after OS-user, type, and symlink checks."""
    directory = _diagnostic_directory(state_dir, create=False)
    path = _reference_path(directory, reference)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise NativeDiagnosticError("diagnostic is unavailable") from exc
    try:
        details = os.fstat(descriptor)
        _require_private_file(details)
        if details.st_size > NATIVE_DIAGNOSTIC_MAX_BYTES:
            raise NativeDiagnosticError("diagnostic exceeds the retention limit")
        current = time.time() if now is None else now
        if current - details.st_mtime >= NATIVE_DIAGNOSTIC_TTL_SECONDS:
            raise NativeDiagnosticError("diagnostic has expired")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            return stream.read(NATIVE_DIAGNOSTIC_MAX_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "NATIVE_DIAGNOSTIC_DIR_NAME",
    "NATIVE_DIAGNOSTIC_MAX_BYTES",
    "NATIVE_DIAGNOSTIC_MAX_FILES",
    "NATIVE_DIAGNOSTIC_TTL_SECONDS",
    "NativeDiagnosticError",
    "NativeDiagnosticReceipt",
    "PERMISSION_BYPASS_UNACCEPTED",
    "classify_native_failure",
    "cleanup_native_diagnostics",
    "read_native_diagnostic",
    "store_native_diagnostic",
]
