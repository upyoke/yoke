"""Machine-user-local retention for every native spawn and resume capture.

One capture per attempt, named by the launch id that spawned the native or the
wake attempt id that resumed it, in one directory shared by every harness. The
name is the join key: a seat that knows either identifier knows the file, and
nothing has to record a second mapping to find it again.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import time
from uuid import UUID

from yoke_contracts.session_control.evidence import (
    NATIVE_DIAGNOSTIC_REFERENCE_PATTERN,
)
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_DISCLAIMER_REFUSAL,
)
from yoke_harness.session_relay_native_capture_format import (
    CAPTURE_MAX_BYTES,
    NativeCapture,
    compose_capture,
    parse_capture,
    utc_stamp,
)
from yoke_harness.session_relay_schedule import relay_state_dir


NATIVE_DIAGNOSTIC_DIR_NAME = "native-diagnostics"
NATIVE_DIAGNOSTIC_MAX_BYTES = CAPTURE_MAX_BYTES
#: Enough captures that a burst of launches cannot evict the one being read.
#: Six launches a minute is an ordinary fleet moment, and a cap of a few dozen
#: discarded the failures an operator went looking for minutes later.
NATIVE_DIAGNOSTIC_MAX_FILES = 256
NATIVE_DIAGNOSTIC_TTL_SECONDS = 7 * 24 * 60 * 60
_FILE_SUFFIX = ".capture"
PERMISSION_BYPASS_UNACCEPTED = "permission_bypass_unaccepted"
MODEL_COMBO_UNSUPPORTED = "model_combo_unsupported"
_BACKGROUND_IN_USE_MARKERS = (
    b"session is already in use",
    b"conversation is already in use",
    b"already in use by another process",
    b"session is currently in use",
)
_MODEL_COMBO_MARKERS = (
    "invalid value for '--model'",
    'invalid value for "--model"',
    "invalid value for '--effort'",
    'invalid value for "--effort"',
    "unknown model",
    "unsupported model",
    "model is not supported",
    "model does not support",
    "invalid model",
    "context window is not supported",
    "context length is not supported",
)


class NativeDiagnosticError(RuntimeError):
    """A private native diagnostic could not be stored or read safely."""


@dataclass(frozen=True)
class NativeDiagnosticReceipt:
    reference: str
    fingerprint_sha256: str
    expires_at: int


def diagnostic_reference(identifier: str) -> str:
    """Return the capture reference for one launch id or wake attempt id."""
    try:
        return f"nd-{UUID(str(identifier).strip())}"
    except (AttributeError, TypeError, ValueError) as exc:
        raise NativeDiagnosticError(
            "diagnostic reference needs a launch id or wake attempt id"
        ) from exc


def classify_native_failure(stderr: bytes) -> str:
    """Map private native stderr to a small non-secret failure taxonomy."""
    lowered = bytes(stderr).lower()
    if CLAUDE_BYPASS_DISCLAIMER_REFUSAL.encode() in lowered:
        return PERMISSION_BYPASS_UNACCEPTED
    if b"no conversation found with session id" in lowered:
        return "no_conversation_found"
    if any(marker in lowered for marker in _BACKGROUND_IN_USE_MARKERS):
        return "background_session_in_use"
    if model_combo_rejection_detail(stderr):
        return MODEL_COMBO_UNSUPPORTED
    return "process_exit"


def model_combo_rejection_detail(output: bytes) -> str | None:
    """Return one bounded vendor rejection line only for a model-knob error."""
    text = bytes(output or b"").decode("utf-8", errors="replace")
    for raw in text.splitlines():
        line = " ".join(raw.strip().split())
        lowered = line.lower()
        if line and any(marker in lowered for marker in _MODEL_COMBO_MARKERS):
            return line[:128]
    return None


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


def native_diagnostic_path(
    reference: str,
    *,
    state_dir: Path | None = None,
    create: bool = True,
) -> Path:
    """Return where the capture named ``reference`` lives on this machine."""
    return _reference_path(
        _diagnostic_directory(state_dir, create=create),
        reference,
    )


def write_native_capture(
    path: Path,
    payload: bytes,
) -> None:
    """Replace one capture's bytes owner-only, refusing an unsafe target."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise NativeDiagnosticError("diagnostic could not be created") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            raise NativeDiagnosticError("diagnostic target is unsafe")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload[:NATIVE_DIAGNOSTIC_MAX_BYTES])
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def store_native_diagnostic(
    stdout: bytes,
    stderr: bytes,
    *,
    reference: str,
    exit_code: int | None = None,
    state_dir: Path | None = None,
    now: float | None = None,
) -> NativeDiagnosticReceipt:
    """Persist one finished native's bounded streams under its own identifier."""
    current = time.time() if now is None else now
    directory = _diagnostic_directory(state_dir, create=True)
    payload = compose_capture(
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        exit_code=exit_code,
        exit_at=utc_stamp(current),
    )
    write_native_capture(_reference_path(directory, reference), payload)
    # After the write, so this capture counts against the retention cap
    # rather than pushing the directory one file past it every time.
    cleanup_native_diagnostics(state_dir, now=current)
    return NativeDiagnosticReceipt(
        reference,
        hashlib.sha256(payload).hexdigest(),
        int(current) + NATIVE_DIAGNOSTIC_TTL_SECONDS,
    )


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


def read_native_capture(path: Path | None) -> NativeCapture | None:
    """Read one capture by path, or ``None`` when it is absent or not one."""
    if path is None:
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return parse_capture(payload[: NATIVE_DIAGNOSTIC_MAX_BYTES + 1])


__all__ = [
    "NATIVE_DIAGNOSTIC_DIR_NAME",
    "NATIVE_DIAGNOSTIC_MAX_BYTES",
    "NATIVE_DIAGNOSTIC_MAX_FILES",
    "NATIVE_DIAGNOSTIC_TTL_SECONDS",
    "NativeDiagnosticError",
    "NativeDiagnosticReceipt",
    "MODEL_COMBO_UNSUPPORTED",
    "PERMISSION_BYPASS_UNACCEPTED",
    "classify_native_failure",
    "cleanup_native_diagnostics",
    "diagnostic_reference",
    "native_diagnostic_path",
    "read_native_capture",
    "read_native_diagnostic",
    "model_combo_rejection_detail",
    "store_native_diagnostic",
    "write_native_capture",
]
