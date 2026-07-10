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


class CredentialFileError(RuntimeError):
    """A credential document or its containing directory is unsafe."""


def read_json_document(path: str | Path) -> dict[str, Any]:
    selected = Path(path).expanduser()
    _assert_secure_parent(selected.parent)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(selected, flags)
    except OSError as exc:
        raise CredentialFileError(f"GitHub App credential is missing: {selected}") from exc
    try:
        _assert_owner_only_file(os.fstat(descriptor), selected)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            payload = json.load(stream)
    except ValueError as exc:
        raise CredentialFileError(
            "GitHub App credential is not a credential document; reconnect GitHub"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise CredentialFileError("GitHub App credential document must be an object")
    return payload


def write_json_document(path: str | Path, payload: Mapping[str, Any]) -> Path:
    selected = Path(path).expanduser()
    selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_secure_parent(selected.parent)
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{selected.name}.", suffix=".tmp", dir=selected.parent
    )
    tmp_path = Path(raw_tmp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(dict(payload), stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, selected)
        _fsync_directory(selected.parent)
    except Exception:
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


@contextmanager
def exclusive_lock(path: str | Path) -> Iterator[None]:
    selected = Path(path).expanduser()
    selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_secure_parent(selected.parent)
    lock_path = selected.with_name(selected.name + ".lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        _assert_owner_only_file(os.fstat(descriptor), lock_path)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _assert_secure_parent(path: Path) -> None:
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
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CredentialFileError(
            f"GitHub App credential directory permissions must be 0700: {path}"
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
    "delete_json_document",
    "exclusive_lock",
    "read_json_document",
    "write_json_document",
]
