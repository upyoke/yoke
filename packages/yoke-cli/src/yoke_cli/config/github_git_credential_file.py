"""Race-safe owner-only file operations for GitHub App credentials."""

from __future__ import annotations

if __package__:
    from yoke_contracts import platform_file_lock, platform_file_sync
    from yoke_contracts.designed_wait import announce_designed_wait
    from yoke_contracts.machine_config.directories import create_private_directory
    from yoke_cli.config import github_git_credential_permissions
else:
    import _yoke_platform_file_lock as platform_file_lock
    import _yoke_platform_file_sync as platform_file_sync
    import _yoke_github_git_credential_permissions as github_git_credential_permissions
    from _yoke_designed_wait import announce_designed_wait
    from _yoke_private_directories import create_private_directory

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator, Mapping


MAX_CREDENTIAL_DOCUMENT_BYTES = 64 * 1024
# One refresh exchange per holder; a bounded wait reports retryable contention.
CREDENTIAL_LOCK_WAIT_SECONDS = 20.0
_LOCK_POLL_SECONDS = 0.05
_LOCK_POLL_MAX_SECONDS = 0.5


class CredentialFileError(RuntimeError):
    """A credential document or its containing directory is unsafe."""


class CredentialFileBusy(CredentialFileError):
    """Another process held the credential lock for the whole wait."""


def read_json_document(
    path: str | Path,
    *,
    require_private_parent: bool = True,
) -> dict[str, Any]:
    selected = Path(path).expanduser()
    github_git_credential_permissions.assert_secure_parent(
        selected.parent,
        CredentialFileError,
        require_private=require_private_parent,
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(selected, flags)
    except OSError as exc:
        raise CredentialFileError(
            f"GitHub App credential is missing: {selected}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        github_git_credential_permissions.assert_owner_only_file(
            info, selected, CredentialFileError
        )
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
    serialized = (json.dumps(dict(payload), sort_keys=True) + "\n").encode("utf-8")
    if len(serialized) > MAX_CREDENTIAL_DOCUMENT_BYTES:
        raise CredentialFileError(
            "GitHub App credential document is too large; reconnect GitHub"
        )
    create_private_directory(selected.parent)
    github_git_credential_permissions.assert_secure_parent(
        selected.parent, CredentialFileError
    )
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
        platform_file_sync.sync_directory(selected.parent)
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
        platform_file_sync.sync_directory(selected.parent)
        return True


def quarantine_json_document(
    path: str | Path,
    quarantine_path: str | Path,
) -> bool:
    """Atomically move a credential to a non-live, retryable deletion name."""
    return _move_under_lock(path, quarantine_path, "quarantine", "quarantined")


def restore_quarantined_json_document(
    quarantine_path: str | Path,
    path: str | Path,
) -> bool:
    """Restore a quarantine when the config still references the credential."""
    return _move_under_lock(quarantine_path, path, "restore", "restored")


def _move_under_lock(
    source_path: str | Path, target_path: str | Path, action: str, done: str
) -> bool:
    """Rename *source_path* onto *target_path* under the source's lock."""
    source = Path(source_path).expanduser()
    target = Path(target_path).expanduser()
    if source.parent != target.parent:
        raise CredentialFileError(
            f"GitHub App credential {action} must stay in the same directory"
        )
    with exclusive_lock(source):
        try:
            source.lstat()
        except FileNotFoundError:
            return False
        try:
            os.replace(source, target)
            platform_file_sync.sync_directory(source.parent)
        except OSError as exc:
            raise CredentialFileError(
                f"GitHub App credential could not be {done}"
            ) from exc
    return True


@contextmanager
def exclusive_lock(
    path: str | Path,
    *,
    wait_seconds: float = CREDENTIAL_LOCK_WAIT_SECONDS,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> Iterator[None]:
    selected = Path(path).expanduser()
    selected_lock_path = lock_path(selected)
    try:
        create_private_directory(selected.parent)
        github_git_credential_permissions.assert_secure_parent(
            selected.parent, CredentialFileError
        )
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(selected_lock_path, flags, 0o600)
    except OSError as exc:
        raise CredentialFileError(
            f"GitHub App credential lock could not be opened: {selected_lock_path}"
        ) from exc
    try:
        try:
            os.fchmod(descriptor, 0o600)
            github_git_credential_permissions.assert_owner_only_file(
                os.fstat(descriptor), selected_lock_path, CredentialFileError
            )
            _wait_for_exclusive_lock(
                descriptor,
                selected_lock_path,
                wait_seconds=wait_seconds,
                sleep=sleep,
                monotonic=monotonic,
            )
            _assert_stable_lock(descriptor, selected_lock_path)
        except OSError as exc:
            raise CredentialFileError(
                "GitHub App credential lock could not be acquired: "
                f"{selected_lock_path}"
            ) from exc
        body_failed = False
        try:
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            try:
                platform_file_lock.release_exclusive(descriptor)
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


def lock_path(path: str | Path) -> Path:
    """Return the stable advisory-lock path for a credential target."""
    selected = Path(path).expanduser()
    return selected.with_name(selected.name + ".lock")


def _assert_stable_lock(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    current = path.lstat()
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise CredentialFileError(
            f"GitHub App credential lock changed while being acquired: {path}"
        )


def _wait_for_exclusive_lock(
    descriptor: int,
    lock_path: Path,
    *,
    wait_seconds: float,
    sleep: Any,
    monotonic: Any,
) -> None:
    """Take the lock, waiting a bounded turn while another process holds it."""
    started = monotonic()
    deadline = started + max(float(wait_seconds), 0.0)
    announced = False
    delay = _LOCK_POLL_SECONDS
    while True:
        try:
            platform_file_lock.acquire_exclusive_nonblocking(descriptor)
            return
        except BlockingIOError:
            remaining = deadline - monotonic()
        if remaining <= 0:
            raise CredentialFileBusy(
                "GitHub App credential lock is held by another local Yoke "
                f"operation after waiting {float(wait_seconds):g}s: {lock_path}"
            )
        if not announced and deadline - remaining - started >= 2.0:
            announced = True
            announce_designed_wait(
                f"another local Yoke operation to release {lock_path}",
                max_wait_seconds=float(wait_seconds),
            )
        sleep(min(delay, remaining))
        delay = min(delay * 2, _LOCK_POLL_MAX_SECONDS)


__all__ = [
    "CREDENTIAL_LOCK_WAIT_SECONDS",
    "CredentialFileBusy",
    "CredentialFileError",
    "MAX_CREDENTIAL_DOCUMENT_BYTES",
    "delete_json_document",
    "exclusive_lock",
    "lock_path",
    "quarantine_json_document",
    "read_json_document",
    "restore_quarantined_json_document",
    "write_json_document",
]
