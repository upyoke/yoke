"""Safely copy root-only self-host mounts into runtime-owned files."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Mapping

from yoke_core.api.oidc_config import OIDC_CLIENT_SECRET_FILE_ENV
from yoke_core.domain.db_backend import PG_DSN_FILE_ENV
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    GITHUB_APP_PRIVATE_KEY_MAX_BYTES,
)


SELF_HOST_SOURCE_SECRETS_DIR = Path("/run/secrets")
SELF_HOST_RUNTIME_SECRETS_DIR = Path("/run/yoke-runtime-secrets")
_TEXT_SECRET_MAX_BYTES = 1 << 16
_SECRET_READ_CHUNK_BYTES = _TEXT_SECRET_MAX_BYTES


class SelfHostServerBootstrapError(RuntimeError):
    """Self-host secret materialization or privilege drop was unsafe."""


@dataclass(frozen=True)
class _SecretSpec:
    env_name: str
    file_name: str
    required: bool
    max_bytes: int


_SECRET_SPECS = (
    _SecretSpec(PG_DSN_FILE_ENV, "yoke-db-dsn", True, _TEXT_SECRET_MAX_BYTES),
    _SecretSpec(
        OIDC_CLIENT_SECRET_FILE_ENV,
        "yoke-oidc-client-secret",
        False,
        _TEXT_SECRET_MAX_BYTES,
    ),
    _SecretSpec(
        GITHUB_APP_PRIVATE_KEY_FILE_ENV,
        "yoke-github-app-private-key",
        False,
        GITHUB_APP_PRIVATE_KEY_MAX_BYTES,
    ),
)


def materialize_self_host_runtime_secrets(
    env: Mapping[str, str],
    *,
    source_dir: Path = SELF_HOST_SOURCE_SECRETS_DIR,
    target_dir: Path = SELF_HOST_RUNTIME_SECRETS_DIR,
    runtime_uid: int,
    runtime_gid: int,
    expected_source_uid: int = 0,
    require_read_only_sources: bool = True,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    """Copy allowlisted root-only mounts into a private runtime directory."""
    _seal_source_directory(source_dir, expected_uid=expected_source_uid)
    _prepare_runtime_directory(
        target_dir,
        bootstrap_uid=os.geteuid(),
        bootstrap_gid=os.getegid(),
    )
    rewritten = dict(env)
    targets: list[Path] = []
    for spec in _SECRET_SPECS:
        configured = str(env.get(spec.env_name) or "").strip()
        expected_source = source_dir / spec.file_name
        if not configured:
            if spec.required:
                raise SelfHostServerBootstrapError(
                    f"{spec.env_name} must name the bundled {spec.file_name} secret"
                )
            continue
        if Path(configured) != expected_source:
            raise SelfHostServerBootstrapError(
                f"{spec.env_name} must name the allowlisted bundled secret"
            )
        payload = _read_sealed_source_secret(
            expected_source,
            expected_uid=expected_source_uid,
            max_bytes=spec.max_bytes,
            require_read_only_mount=require_read_only_sources,
        )
        target = target_dir / spec.file_name
        _atomic_runtime_secret(
            target,
            payload,
            uid=runtime_uid,
            gid=runtime_gid,
        )
        rewritten[spec.env_name] = str(target)
        targets.append(target)
    _finish_runtime_directory(target_dir, uid=runtime_uid, gid=runtime_gid)
    return rewritten, tuple(targets)


def _seal_source_directory(path: Path, *, expected_uid: int) -> None:
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid:
            raise SelfHostServerBootstrapError(
                "self-host source secret directory is not trusted"
            )
        os.chmod(path, 0o700)
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            "self-host source secret directory cannot be sealed"
        ) from exc


def _prepare_runtime_directory(
    path: Path,
    *,
    bootstrap_uid: int,
    bootstrap_gid: int,
) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise SelfHostServerBootstrapError(
                "self-host runtime secret target must be a real directory"
            )
        os.chown(path, bootstrap_uid, bootstrap_gid)
        os.chmod(path, 0o700)
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    raise SelfHostServerBootstrapError(
                        "self-host runtime secret directory contains "
                        "an unexpected directory"
                    )
                os.unlink(entry.path)
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            "self-host runtime secret directory cannot be prepared"
        ) from exc


def _finish_runtime_directory(path: Path, *, uid: int, gid: int) -> None:
    try:
        os.chmod(path, 0o700)
        os.chown(path, uid, gid)
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            "self-host runtime secret directory ownership cannot be finalized"
        ) from exc


def _read_sealed_source_secret(
    path: Path,
    *,
    expected_uid: int,
    max_bytes: int,
    require_read_only_mount: bool,
) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        if require_read_only_mount:
            _assert_read_only_source_mount(path)
        owner_only = not mode & 0o077
        sealed_read_only_mount = require_read_only_mount and not mode & 0o022
        if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid:
            raise SelfHostServerBootstrapError(
                f"self-host source secret is not root-only: {path.name}"
            )
        link_safe = info.st_nlink == 1 or require_read_only_mount
        if not link_safe or not mode & 0o400:
            raise SelfHostServerBootstrapError(
                f"self-host source secret is not root-only: {path.name}"
            )
        if not (owner_only or sealed_read_only_mount):
            raise SelfHostServerBootstrapError(
                f"self-host source secret is not root-only: {path.name}"
            )
        if info.st_size <= 0:
            raise SelfHostServerBootstrapError(
                f"self-host source secret is empty: {path.name}"
            )
        if info.st_size > max_bytes:
            raise SelfHostServerBootstrapError(
                f"self-host source secret exceeds its size limit: {path.name}"
            )
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(_SECRET_READ_CHUNK_BYTES, max_bytes + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise SelfHostServerBootstrapError(
                    f"self-host source secret exceeds its size limit: {path.name}"
                )
        payload = b"".join(chunks)
    except SelfHostServerBootstrapError:
        raise
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            f"self-host source secret cannot be safely opened: {path.name}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not payload:
        raise SelfHostServerBootstrapError(
            f"self-host source secret is empty: {path.name}"
        )
    return payload


def _assert_read_only_source_mount(
    path: Path,
    *,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
) -> None:
    try:
        lines = mountinfo_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            "self-host source mount state cannot be inspected"
        ) from exc
    selected = str(path.resolve(strict=False))
    for line in lines:
        fields = line.split()
        if len(fields) < 6 or _unescape_mount_path(fields[4]) != selected:
            continue
        if "ro" in fields[5].split(","):
            return
        break
    raise SelfHostServerBootstrapError(
        f"self-host source secret is not a read-only mount: {path.name}"
    )


def _unescape_mount_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _atomic_runtime_secret(
    target: Path,
    payload: bytes,
    *,
    uid: int,
    gid: int,
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SelfHostServerBootstrapError(
                    f"self-host runtime secret write stalled: {target.name}"
                )
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, uid, gid)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, target)
        directory_descriptor = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "SELF_HOST_RUNTIME_SECRETS_DIR",
    "SELF_HOST_SOURCE_SECRETS_DIR",
    "SelfHostServerBootstrapError",
    "materialize_self_host_runtime_secrets",
]
