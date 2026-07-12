"""Race-safe owner-only file operations for GitHub App credentials."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator, Mapping


MAX_CREDENTIAL_DOCUMENT_BYTES = 64 * 1024


class CredentialFileError(RuntimeError):
    """A credential document or its containing directory is unsafe."""


def read_json_document(
    path: str | Path, *, require_private_parent: bool = True,
) -> dict[str, Any]:
    selected = Path(path).expanduser()
    _assert_secure_parent(
        selected.parent, require_private=require_private_parent,
    )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(selected, flags)
    except OSError as exc:
        raise CredentialFileError(f"GitHub App credential is missing: {selected}") from exc
    try:
        info = os.fstat(descriptor)
        _assert_owner_only_file(info, selected)
        if info.st_size > MAX_CREDENTIAL_DOCUMENT_BYTES:
            raise CredentialFileError(
                "GitHub App credential document is too large; reconnect GitHub"
            )
        raw = _read_bounded(descriptor, MAX_CREDENTIAL_DOCUMENT_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CredentialFileError(
            "GitHub App credential is not a credential document; reconnect GitHub"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise CredentialFileError("GitHub App credential document must be an object")
    return payload


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 16 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > maximum:
        raise CredentialFileError(
            "GitHub App credential document is too large; reconnect GitHub"
        )
    return payload


def write_json_document(path: str | Path, payload: Mapping[str, Any]) -> Path:
    selected = Path(path).expanduser()
    serialized = (
        json.dumps(dict(payload), sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(serialized) > MAX_CREDENTIAL_DOCUMENT_BYTES:
        raise CredentialFileError(
            "GitHub App credential document is too large; reconnect GitHub"
        )
    selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_secure_parent(selected.parent)
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{selected.name}.", suffix=".tmp", dir=selected.parent
    )
    tmp_path = Path(raw_tmp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, selected)
        _fsync_directory(selected.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        tmp_path.unlink(missing_ok=True)
        raise
    return selected


def delete_json_document(path: str | Path) -> bool:
    """Delete a credential under its stable lock, leaving the lock inode."""
    selected = Path(path).expanduser()
    with exclusive_lock(selected):
        try:
            selected.unlink()
        except FileNotFoundError:
            return False
        _fsync_directory(selected.parent)
        return True


def quarantine_json_document(
    path: str | Path,
    quarantine_path: str | Path,
) -> bool:
    """Atomically move a credential to a non-live, retryable deletion name."""
    selected = Path(path).expanduser()
    quarantine = Path(quarantine_path).expanduser()
    if selected.parent != quarantine.parent:
        raise CredentialFileError(
            "GitHub App credential quarantine must stay in the same directory"
        )
    with exclusive_lock(selected):
        try:
            selected.lstat()
        except FileNotFoundError:
            return False
        try:
            os.replace(selected, quarantine)
            _fsync_directory(selected.parent)
        except OSError as exc:
            raise CredentialFileError(
                "GitHub App credential could not be quarantined"
            ) from exc
    return True


def restore_quarantined_json_document(
    quarantine_path: str | Path,
    path: str | Path,
) -> bool:
    """Restore a quarantine when the config still references the credential."""
    quarantine = Path(quarantine_path).expanduser()
    selected = Path(path).expanduser()
    if selected.parent != quarantine.parent:
        raise CredentialFileError(
            "GitHub App credential restore must stay in the same directory"
        )
    with exclusive_lock(quarantine):
        try:
            quarantine.lstat()
        except FileNotFoundError:
            return False
        try:
            os.replace(quarantine, selected)
            _fsync_directory(selected.parent)
        except OSError as exc:
            raise CredentialFileError(
                "GitHub App credential could not be restored"
            ) from exc
    return True


@contextmanager
def exclusive_lock(path: str | Path) -> Iterator[None]:
    selected = Path(path).expanduser()
    lock_path = selected.with_name(selected.name + ".lock")
    try:
        selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _assert_secure_parent(selected.parent)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise CredentialFileError(
            f"GitHub App credential lock could not be opened: {lock_path}"
        ) from exc
    try:
        try:
            os.fchmod(descriptor, 0o600)
            _assert_owner_only_file(os.fstat(descriptor), lock_path)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise CredentialFileError(
                f"GitHub App credential lock could not be acquired: {lock_path}"
            ) from exc
        body_failed = False
        try:
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError as exc:
                if not body_failed:
                    raise CredentialFileError(
                        "GitHub App credential lock could not be released"
                    ) from exc
    finally:
        try:
            os.close(descriptor)
        except OSError as exc:
            if not locals().get("body_failed", False):
                raise CredentialFileError(
                    "GitHub App credential lock could not be closed"
                ) from exc


def _assert_secure_parent(
    path: Path, *, require_private: bool = True,
) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CredentialFileError(
            f"GitHub App credential directory is missing: {path}"
        ) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise CredentialFileError(
            f"GitHub App credential parent must be a directory: {path}"
        )
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise CredentialFileError(
            f"GitHub App credential directory is not owned by the current user: {path}"
        )
    forbidden_mode = 0o077 if require_private else 0o022
    if stat.S_IMODE(info.st_mode) & forbidden_mode:
        raise CredentialFileError(
            "GitHub App credential directory permissions are unsafe: "
            f"{path}"
        )


def _assert_owner_only_file(info: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise CredentialFileError(
            f"GitHub App credential must be a regular file: {path}"
        )
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise CredentialFileError(
            f"GitHub App credential is not owned by the current user: {path}"
        )
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CredentialFileError(
            f"GitHub App credential permissions must be 0600: {path}"
        )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CredentialFileError",
    "MAX_CREDENTIAL_DOCUMENT_BYTES",
    "delete_json_document",
    "exclusive_lock",
    "quarantine_json_document",
    "read_json_document",
    "restore_quarantined_json_document",
    "write_json_document",
]
