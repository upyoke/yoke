"""Versioned atomic installation for the standalone Git credential helper."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterator

from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_document
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_launcher
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import (
    github_oauth_transport,
    github_response_safety,
    github_service_profile_proof,
)
from yoke_contracts import api_urls, github_app_tokens, github_origin


STABLE_HELPER_FILE_NAME = github_git_credential_launcher.BUNDLE_HELPER_NAME
STABLE_STORE_FILE_NAME = github_git_credential_launcher.BUNDLE_STORE_NAME
STABLE_ORIGIN_FILE_NAME = github_git_credential_launcher.BUNDLE_ORIGIN_NAME
STABLE_API_URLS_NAME = github_git_credential_launcher.BUNDLE_API_URLS_NAME
STABLE_FILE_IO_NAME = github_git_credential_launcher.BUNDLE_FILE_IO_NAME
STABLE_DOCUMENT_NAME = github_git_credential_launcher.BUNDLE_DOCUMENT_NAME
STABLE_TOKEN_CONTRACT_NAME = (
    github_git_credential_launcher.BUNDLE_TOKEN_CONTRACT_NAME
)
STABLE_RESPONSE_SAFETY_NAME = (
    github_git_credential_launcher.BUNDLE_RESPONSE_SAFETY_NAME
)
STABLE_OAUTH_TRANSPORT_NAME = (
    github_git_credential_launcher.BUNDLE_OAUTH_TRANSPORT_NAME
)
STABLE_SERVICE_PROFILE_PROOF_NAME = (
    github_git_credential_launcher.BUNDLE_SERVICE_PROFILE_PROOF_NAME
)


class GitHubCredentialBundleError(RuntimeError):
    """An existing helper bundle cannot be safely verified or replaced."""


MAX_HELPER_SOURCE_BYTES = 2 * 1024 * 1024


def install(target_dir: Path) -> Path:
    """Atomically select one complete immutable helper bundle."""
    target_dir.mkdir(parents=True, exist_ok=True)
    helper_path = target_dir / STABLE_HELPER_FILE_NAME
    sources = _bundle_sources()
    bundle_name = _bundle_name(sources)
    with _bundle_install_lock(target_dir):
        _install_immutable_bundle(target_dir, bundle_name, sources)
        _publish_bundle_pointer(target_dir, bundle_name)
        _publish_launcher(helper_path)
    return helper_path


def _bundle_sources() -> tuple[tuple[Path, str], ...]:
    return (
        (Path(github_origin.__file__), STABLE_ORIGIN_FILE_NAME),
        (Path(api_urls.__file__), STABLE_API_URLS_NAME),
        (Path(github_app_tokens.__file__), STABLE_TOKEN_CONTRACT_NAME),
        (Path(github_response_safety.__file__), STABLE_RESPONSE_SAFETY_NAME),
        (Path(github_oauth_transport.__file__), STABLE_OAUTH_TRANSPORT_NAME),
        (
            Path(github_service_profile_proof.__file__),
            STABLE_SERVICE_PROFILE_PROOF_NAME,
        ),
        (Path(github_git_credential_file.__file__), STABLE_FILE_IO_NAME),
        (Path(github_git_credential_document.__file__), STABLE_DOCUMENT_NAME),
        (Path(github_git_credential_store.__file__), STABLE_STORE_FILE_NAME),
        (Path(github_git_credential_helper.__file__), STABLE_HELPER_FILE_NAME),
    )


def _bundle_name(sources: tuple[tuple[Path, str], ...]) -> str:
    digest = hashlib.sha256()
    for source, target_name in sources:
        digest.update(target_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_safe_read_source(source))
        digest.update(b"\0")
    return digest.hexdigest()


def _install_immutable_bundle(
    target_dir: Path,
    bundle_name: str,
    sources: tuple[tuple[Path, str], ...],
) -> Path:
    bundle_root = target_dir / github_git_credential_launcher.BUNDLE_ROOT_NAME
    bundle_root.mkdir(mode=0o755, exist_ok=True)
    target = bundle_root / bundle_name
    if target.exists():
        _verify_bundle(target, sources)
        return target
    temp = Path(tempfile.mkdtemp(prefix=".bundle-", dir=bundle_root))
    try:
        os.chmod(temp, 0o755)
        for source, target_name in sources:
            _write_unpublished_source(source, temp / target_name)
        _fsync_directory(temp)
        os.replace(temp, target)
        _fsync_directory(bundle_root)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return target


def _verify_bundle(
    bundle: Path,
    sources: tuple[tuple[Path, str], ...],
) -> None:
    expected_names = {target_name for _source, target_name in sources}
    try:
        if not stat.S_ISDIR(bundle.lstat().st_mode) or bundle.is_symlink():
            raise GitHubCredentialBundleError(
                "installed GitHub helper bundle is not a directory"
            )
        actual_names = {path.name for path in bundle.iterdir()}
    except OSError as exc:
        raise GitHubCredentialBundleError(
            "installed GitHub helper bundle is unreadable"
        ) from exc
    if actual_names != expected_names:
        raise GitHubCredentialBundleError(
            "installed GitHub helper bundle is not immutable"
        )
    for source, target_name in sources:
        if _safe_read_source(bundle / target_name) != _safe_read_source(source):
            raise GitHubCredentialBundleError(
                "installed GitHub helper bundle is not immutable"
            )


def _write_unpublished_source(source: Path, target: Path) -> None:
    payload = _safe_read_source(source)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_bundle_pointer(target_dir: Path, bundle_name: str) -> None:
    _atomic_replace_bytes(
        f"{bundle_name}\n".encode("ascii"),
        target_dir / github_git_credential_launcher.BUNDLE_POINTER_NAME,
    )


def _publish_launcher(helper_path: Path) -> None:
    _atomic_replace_bytes(
        _safe_read_source(Path(github_git_credential_launcher.__file__)), helper_path,
    )


def _safe_read_source(path: Path) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GitHubCredentialBundleError(
            "GitHub helper bundle source is unreadable"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > MAX_HELPER_SOURCE_BYTES
        ):
            raise GitHubCredentialBundleError(
                "GitHub helper bundle source is unsafe"
            )
        remaining = MAX_HELPER_SOURCE_BYTES + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_HELPER_SOURCE_BYTES:
            raise GitHubCredentialBundleError(
                "GitHub helper bundle source is too large"
            )
        return payload
    finally:
        os.close(descriptor)


@contextmanager
def _bundle_install_lock(target_dir: Path) -> Iterator[None]:
    lock_path = target_dir / ".yoke-github-helper-install.lock"
    descriptor = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_replace_bytes(payload: bytes, target: Path) -> None:
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    tmp_path = Path(raw_tmp)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        tmp_path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "STABLE_API_URLS_NAME", "STABLE_DOCUMENT_NAME", "STABLE_FILE_IO_NAME",
    "STABLE_HELPER_FILE_NAME",
    "STABLE_OAUTH_TRANSPORT_NAME", "STABLE_ORIGIN_FILE_NAME",
    "STABLE_RESPONSE_SAFETY_NAME", "STABLE_STORE_FILE_NAME",
    "STABLE_SERVICE_PROFILE_PROOF_NAME",
    "STABLE_TOKEN_CONTRACT_NAME", "install",
    "GitHubCredentialBundleError", "MAX_HELPER_SOURCE_BYTES",
]
