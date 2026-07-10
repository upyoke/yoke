"""Typed control-plane GitHub App configuration and secret resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)


GITHUB_APP_ISSUER_ENV = "YOKE_GITHUB_APP_ISSUER"
GITHUB_APP_PRIVATE_KEY_FILE_ENV = "YOKE_GITHUB_APP_PRIVATE_KEY_FILE"
GITHUB_APP_API_URL_ENV = "YOKE_GITHUB_APP_API_URL"


class GitHubAppControlPlaneConfigError(ValueError):
    """Raised when global GitHub App configuration is missing or unsafe."""


@dataclass(frozen=True)
class GitHubAppControlPlaneConfig:
    issuer: str
    private_key_pem: str = field(repr=False)
    endpoint: GitHubApiEndpoint
    private_key_file: str


def load_github_app_endpoint(
    env: Mapping[str, str] | None = None,
) -> GitHubApiEndpoint:
    """Load the exact API endpoint shared by user and installation auth."""
    source = os.environ if env is None else env
    try:
        return validate_github_api_endpoint(source.get(GITHUB_APP_API_URL_ENV))
    except GitHubApiOriginError as exc:
        raise GitHubAppControlPlaneConfigError(str(exc)) from exc


def load_github_app_control_plane_config(
    env: Mapping[str, str] | None = None,
) -> GitHubAppControlPlaneConfig:
    """Resolve the global issuer and owner-only mounted private-key file."""
    source = os.environ if env is None else env
    issuer = validate_github_app_issuer(source.get(GITHUB_APP_ISSUER_ENV))
    raw_path = str(source.get(GITHUB_APP_PRIVATE_KEY_FILE_ENV) or "").strip()
    if not raw_path:
        raise GitHubAppControlPlaneConfigError(
            f"{GITHUB_APP_PRIVATE_KEY_FILE_ENV} is required"
        )
    key_path = Path(raw_path).expanduser()
    private_key = _read_owner_only_secret(key_path)
    return GitHubAppControlPlaneConfig(
        issuer=issuer,
        private_key_pem=private_key,
        endpoint=load_github_app_endpoint(source),
        private_key_file=str(key_path),
    )


def _read_owner_only_secret(path: Path) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise GitHubAppControlPlaneConfigError(
            "this platform cannot safely open the GitHub App private-key file"
        )
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GitHubAppControlPlaneConfigError(
            f"GitHub App private-key file cannot be safely opened: {path}"
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise GitHubAppControlPlaneConfigError(
                "GitHub App private-key path must be a regular file"
            )
        resolved_path = _resolved_open_file_path(descriptor, path)
        effective_uid = os.geteuid()
        mode = stat.S_IMODE(file_stat.st_mode)
        service_owned_safe = (
            file_stat.st_uid == effective_uid and not (mode & 0o077)
        )
        root_mount_safe = (
            file_stat.st_uid == 0
            and _is_under_runtime_secrets(resolved_path)
            and not (mode & 0o022)
        )
        if not service_owned_safe and not root_mount_safe:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App private-key file must be owner-only for the service "
                "user, or a root-owned read-only mount under /run/secrets"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = handle.read().strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise GitHubAppControlPlaneConfigError(
            f"GitHub App private-key file cannot be read as UTF-8: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not value:
        raise GitHubAppControlPlaneConfigError(
            "GitHub App private-key file is empty"
        )
    return value


def _resolved_open_file_path(descriptor: int, configured_path: Path) -> Path:
    proc_path = f"/proc/self/fd/{descriptor}"
    try:
        return Path(os.readlink(proc_path)).resolve(strict=False)
    except OSError:
        try:
            return configured_path.resolve(strict=True)
        except OSError as exc:
            raise GitHubAppControlPlaneConfigError(
                f"GitHub App private-key file cannot be resolved: {configured_path}"
            ) from exc


def _is_under_runtime_secrets(path: Path) -> bool:
    try:
        path.relative_to(Path("/run/secrets"))
    except ValueError:
        return False
    return True


def validate_github_app_issuer(value: object) -> str:
    issuer = str(value or "").strip()
    if not issuer:
        raise GitHubAppControlPlaneConfigError(f"{GITHUB_APP_ISSUER_ENV} is required")
    if re.fullmatch(r"[A-Za-z0-9._-]+", issuer) is None:
        raise GitHubAppControlPlaneConfigError(
            "GitHub App issuer must be a client id or numeric app id"
        )
    return issuer


__all__ = [
    "GITHUB_APP_API_URL_ENV",
    "GITHUB_APP_ISSUER_ENV",
    "GITHUB_APP_PRIVATE_KEY_FILE_ENV",
    "GitHubAppControlPlaneConfig",
    "GitHubAppControlPlaneConfigError",
    "load_github_app_control_plane_config",
    "load_github_app_endpoint",
    "validate_github_app_issuer",
]
