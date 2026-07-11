"""Typed control-plane GitHub App configuration and secret resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from pydantic import ValidationError
from yoke_contracts.github_app_public import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
    GitHubAppAdvertisement,
    GitHubAppPublicProfile,
    GitHubAppUnavailable,
    parse_github_app_advertisement,
)
from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)


GITHUB_APP_ISSUER_ENV = "YOKE_GITHUB_APP_ISSUER"
GITHUB_APP_PRIVATE_KEY_FILE_ENV = "YOKE_GITHUB_APP_PRIVATE_KEY_FILE"
GITHUB_APP_PRIVATE_KEY_MAX_BYTES = 1024 * 1024

_PUBLIC_IDENTITY_ENV_NAMES = (
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_WEB_URL_ENV,
)
_RUNTIME_CONFIGURATION_ENV_NAMES = (
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    GITHUB_APP_API_URL_ENV,
    *_PUBLIC_IDENTITY_ENV_NAMES,
)


class GitHubAppControlPlaneConfigError(ValueError):
    """Raised when global GitHub App configuration is missing or unsafe."""


@dataclass(frozen=True)
class GitHubAppControlPlaneConfig:
    issuer: str
    private_key_pem: str = field(repr=False)
    endpoint: GitHubApiEndpoint
    private_key_file: str
    public_profile: GitHubAppPublicProfile | None = None


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
    """Resolve the global issuer and access-restricted private-key mount."""
    source = os.environ if env is None else env
    issuer = validate_github_app_issuer(source.get(GITHUB_APP_ISSUER_ENV))
    raw_path = str(source.get(GITHUB_APP_PRIVATE_KEY_FILE_ENV) or "").strip()
    if not raw_path:
        raise GitHubAppControlPlaneConfigError(
            f"{GITHUB_APP_PRIVATE_KEY_FILE_ENV} is required"
        )
    key_path = Path(raw_path).expanduser()
    private_key = _read_restricted_secret(key_path)
    return GitHubAppControlPlaneConfig(
        issuer=issuer,
        private_key_pem=private_key,
        endpoint=load_github_app_endpoint(source),
        private_key_file=str(key_path),
        public_profile=load_github_app_public_profile(source),
    )


def load_github_app_public_profile(
    env: Mapping[str, str] | None = None,
    *,
    strict_partial: bool = False,
) -> GitHubAppPublicProfile | None:
    """Load an optional all-or-none public profile without reading secrets."""
    source = os.environ if env is None else env
    public_values = {
        name: str(source.get(name) or "").strip() for name in _PUBLIC_IDENTITY_ENV_NAMES
    }
    if not any(public_values.values()):
        return None
    missing = [name for name, value in public_values.items() if not value]
    api_url = str(source.get(GITHUB_APP_API_URL_ENV) or "").strip()
    if not api_url:
        missing.append(GITHUB_APP_API_URL_ENV)
    if missing:
        if strict_partial:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App public profile is incomplete"
            )
        return None
    try:
        profile = parse_github_app_advertisement(
            {
                "available": True,
                "client_id": public_values[GITHUB_APP_CLIENT_ID_ENV],
                "app_slug": public_values[GITHUB_APP_SLUG_ENV],
                "app_id": public_values[GITHUB_APP_ID_ENV],
                "api_url": api_url,
                "web_url": public_values[GITHUB_APP_WEB_URL_ENV],
            }
        )
    except (ValidationError, ValueError) as exc:
        if strict_partial:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App public profile is invalid"
            ) from exc
        return None
    if not isinstance(profile, GitHubAppPublicProfile):
        if strict_partial:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App public profile is unavailable"
            )
        return None
    issuer = str(source.get(GITHUB_APP_ISSUER_ENV) or "").strip()
    if issuer and issuer not in {profile.client_id, str(profile.app_id)}:
        if strict_partial:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App public profile does not match the configured issuer"
            )
        return None
    return profile


def github_app_public_advertisement(
    env: Mapping[str, str] | None = None,
) -> GitHubAppAdvertisement:
    """Return a detail-free, network-free health advertisement."""
    source = os.environ if env is None else env
    try:
        config = load_github_app_control_plane_config(source)
    except GitHubAppControlPlaneConfigError:
        return GitHubAppUnavailable()
    return config.public_profile or GitHubAppUnavailable()


def has_github_app_runtime_configuration(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether any private or public GitHub App runtime knob is set."""
    source = os.environ if env is None else env
    return any(
        str(source.get(name) or "").strip() for name in _RUNTIME_CONFIGURATION_ENV_NAMES
    )


def _read_restricted_secret(path: Path) -> str:
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
        if file_stat.st_size > GITHUB_APP_PRIVATE_KEY_MAX_BYTES:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App private-key file exceeds the size limit"
            )
        resolved_path = _resolved_open_file_path(descriptor, path)
        effective_uid = os.geteuid()
        mode = stat.S_IMODE(file_stat.st_mode)
        service_owned_safe = file_stat.st_uid == effective_uid and not (mode & 0o077)
        root_mount_safe = (
            file_stat.st_uid == 0
            and _is_under_runtime_secrets(resolved_path)
            and not (mode & 0o022)
        )
        effective_groups = {os.getegid(), *os.getgroups()}
        group_read_mount_safe = (
            getattr(file_stat, "st_gid", -1) in effective_groups
            and _is_under_runtime_secrets(resolved_path)
            and bool(mode & 0o040)
            and not (mode & 0o027)
        )
        if not (service_owned_safe or root_mount_safe or group_read_mount_safe):
            raise GitHubAppControlPlaneConfigError(
                "GitHub App private-key file must be owner-only for the service "
                "user, root-owned read-only, or group-read-only for the service "
                "group under /run/secrets"
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw_value = handle.read(GITHUB_APP_PRIVATE_KEY_MAX_BYTES + 1)
        if len(raw_value) > GITHUB_APP_PRIVATE_KEY_MAX_BYTES:
            raise GitHubAppControlPlaneConfigError(
                "GitHub App private-key file exceeds the size limit"
            )
        value = raw_value.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise GitHubAppControlPlaneConfigError(
            f"GitHub App private-key file cannot be read as UTF-8: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not value:
        raise GitHubAppControlPlaneConfigError("GitHub App private-key file is empty")
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
    "GITHUB_APP_CLIENT_ID_ENV",
    "GITHUB_APP_ID_ENV",
    "GITHUB_APP_ISSUER_ENV",
    "GITHUB_APP_PRIVATE_KEY_FILE_ENV",
    "GITHUB_APP_PRIVATE_KEY_MAX_BYTES",
    "GITHUB_APP_SLUG_ENV",
    "GITHUB_APP_WEB_URL_ENV",
    "GitHubAppControlPlaneConfig",
    "GitHubAppControlPlaneConfigError",
    "github_app_public_advertisement",
    "has_github_app_runtime_configuration",
    "load_github_app_control_plane_config",
    "load_github_app_endpoint",
    "load_github_app_public_profile",
    "validate_github_app_issuer",
]
