"""Stable entrypoint for an atomically selected Git credential bundle."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import types
from pathlib import Path


BUNDLE_ROOT_NAME = "_yoke_github_helper_bundles"
BUNDLE_POINTER_NAME = "_yoke_github_helper_current"
BUNDLE_HELPER_NAME = "_yoke_github_git_credential_helper.py"
BUNDLE_ORIGIN_NAME = "_yoke_github_origin.py"
BUNDLE_API_URLS_NAME = "_yoke_api_urls.py"
BUNDLE_TOKEN_CONTRACT_NAME = "_yoke_github_app_tokens.py"
BUNDLE_RESPONSE_SAFETY_NAME = "_yoke_github_response_safety.py"
BUNDLE_OAUTH_TRANSPORT_NAME = "_yoke_github_oauth_transport.py"
BUNDLE_SERVICE_PROFILE_PROOF_NAME = "_yoke_github_service_profile_proof.py"
BUNDLE_FILE_IO_NAME = "_yoke_github_git_credential_file.py"
BUNDLE_DOCUMENT_NAME = "_yoke_github_git_credential_document.py"
BUNDLE_STORE_NAME = "_yoke_github_git_credential_store.py"
BUNDLE_MODULE_NAMES = (
    BUNDLE_ORIGIN_NAME,
    BUNDLE_API_URLS_NAME,
    BUNDLE_TOKEN_CONTRACT_NAME,
    BUNDLE_RESPONSE_SAFETY_NAME,
    BUNDLE_OAUTH_TRANSPORT_NAME,
    BUNDLE_SERVICE_PROFILE_PROOF_NAME,
    BUNDLE_FILE_IO_NAME,
    BUNDLE_DOCUMENT_NAME,
    BUNDLE_STORE_NAME,
    BUNDLE_HELPER_NAME,
)
BUNDLE_NAME_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_POINTER_MAX_BYTES = 128
BUNDLE_MODULE_MAX_BYTES = 2 * 1024 * 1024


class GitHubCredentialLauncherError(RuntimeError):
    """The installed helper bundle pointer is absent or unsafe."""


def selected_bundle(site_dir: str | Path | None = None) -> Path:
    """Resolve the complete immutable bundle selected by the stable pointer."""
    root = Path(site_dir) if site_dir is not None else Path(__file__).parent
    pointer = root / BUNDLE_POINTER_NAME
    try:
        bundle_name = _read_regular(
            pointer, maximum=BUNDLE_POINTER_MAX_BYTES,
        ).decode("ascii").strip()
    except (OSError, UnicodeError, GitHubCredentialLauncherError) as exc:
        raise GitHubCredentialLauncherError(
            "GitHub credential helper bundle pointer is unavailable"
        ) from exc
    if not BUNDLE_NAME_PATTERN.fullmatch(bundle_name):
        raise GitHubCredentialLauncherError(
            "GitHub credential helper bundle pointer is invalid"
        )
    bundle = root / BUNDLE_ROOT_NAME / bundle_name
    try:
        info = bundle.lstat()
    except OSError as exc:
        raise GitHubCredentialLauncherError(
            "GitHub credential helper bundle is incomplete"
        ) from exc
    if not stat.S_ISDIR(info.st_mode) or bundle.is_symlink():
        raise GitHubCredentialLauncherError(
            "GitHub credential helper bundle is incomplete"
        )
    _verified_bundle_sources(bundle, expected_hash=bundle_name)
    return bundle


def main() -> None:
    bundle = selected_bundle()
    sources = _verified_bundle_sources(bundle, expected_hash=bundle.name)
    sys.path.insert(0, str(bundle))
    for filename in BUNDLE_MODULE_NAMES[:-1]:
        _load_sibling(bundle / filename, sources[filename])
    helper_path = bundle / BUNDLE_HELPER_NAME
    namespace = {
        "__file__": str(helper_path),
        "__name__": "__main__",
        "__package__": None,
    }
    exec(compile(sources[BUNDLE_HELPER_NAME], str(helper_path), "exec"), namespace)


def _verified_bundle_sources(
    bundle: Path, *, expected_hash: str,
) -> dict[str, bytes]:
    digest = hashlib.sha256()
    sources: dict[str, bytes] = {}
    for filename in BUNDLE_MODULE_NAMES:
        payload = _read_regular(
            bundle / filename, maximum=BUNDLE_MODULE_MAX_BYTES,
        )
        sources[filename] = payload
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    if digest.hexdigest() != expected_hash:
        raise GitHubCredentialLauncherError(
            "GitHub credential helper bundle failed integrity verification"
        )
    return sources


def _read_regular(path: Path, *, maximum: int) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GitHubCredentialLauncherError(
            "GitHub credential helper file is unavailable"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > maximum
        ):
            raise GitHubCredentialLauncherError(
                "GitHub credential helper file is unsafe"
            )
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum:
            raise GitHubCredentialLauncherError(
                "GitHub credential helper file is too large"
            )
        return payload
    finally:
        os.close(descriptor)


def _load_sibling(path: Path, payload: bytes) -> None:
    name = path.stem
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(payload, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise


if __name__ == "__main__":  # pragma: no cover - installed entrypoint
    main()


__all__ = [
    "BUNDLE_HELPER_NAME",
    "BUNDLE_API_URLS_NAME",
    "BUNDLE_FILE_IO_NAME",
    "BUNDLE_DOCUMENT_NAME",
    "BUNDLE_MODULE_MAX_BYTES",
    "BUNDLE_MODULE_NAMES",
    "BUNDLE_OAUTH_TRANSPORT_NAME",
    "BUNDLE_ORIGIN_NAME",
    "BUNDLE_NAME_PATTERN",
    "BUNDLE_POINTER_MAX_BYTES",
    "BUNDLE_POINTER_NAME",
    "BUNDLE_ROOT_NAME",
    "BUNDLE_RESPONSE_SAFETY_NAME",
    "BUNDLE_SERVICE_PROFILE_PROOF_NAME",
    "BUNDLE_STORE_NAME",
    "BUNDLE_TOKEN_CONTRACT_NAME",
    "GitHubCredentialLauncherError",
    "main",
    "selected_bundle",
]
