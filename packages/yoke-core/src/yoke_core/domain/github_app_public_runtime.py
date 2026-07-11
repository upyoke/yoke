"""Startup identity attestation and public GitHub App advertisement."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Mapping

from yoke_contracts.github_app_public import (
    GitHubAppAdvertisement,
    GitHubAppUnavailable,
)

from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfig,
    GitHubAppControlPlaneConfigError,
    has_github_app_runtime_configuration,
    load_github_app_control_plane_config,
)
from yoke_core.domain.github_app_identity import validate_public_profile
from yoke_core.domain.github_app_identity_verification import (
    fetch_authenticated_app_identity,
)


_log = logging.getLogger("yoke.api.startup")
_attested_runtime_fingerprint: bytes | None = None
_attested_public_fingerprint: bytes | None = None


def attest_github_app_runtime_identity(
    env: Mapping[str, str] | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    identity_fetcher: Callable[..., Any] | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Authenticate configured App authority once during process startup."""
    global _attested_public_fingerprint, _attested_runtime_fingerprint
    _attested_runtime_fingerprint = None
    _attested_public_fingerprint = None
    if not has_github_app_runtime_configuration(env):
        return False
    try:
        config = load_github_app_control_plane_config(env)
        identity = (identity_fetcher or fetch_authenticated_app_identity)(
            config,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - startup stays live and logs no detail
        _log.warning(
            "GitHub App runtime identity attestation failed; "
            "startup continued without verified App authority"
        )
        return False

    _attested_runtime_fingerprint = _runtime_fingerprint(config)
    profile = config.public_profile
    if profile is not None:
        try:
            validate_public_profile(identity, profile)
        except Exception:  # noqa: BLE001 - advertisement stays fail-closed
            _log.warning(
                "GitHub App public profile attestation failed; advertisement disabled"
            )
        else:
            _attested_public_fingerprint = _public_fingerprint(config)
    _log.info("GitHub App runtime identity attested")
    return True


def current_github_app_public_advertisement(
    env: Mapping[str, str] | None = None,
) -> GitHubAppAdvertisement:
    """Return the startup-attested profile without making a network request."""
    if _attested_runtime_fingerprint is None or _attested_public_fingerprint is None:
        return GitHubAppUnavailable()
    try:
        config = load_github_app_control_plane_config(env)
    except GitHubAppControlPlaneConfigError:
        return GitHubAppUnavailable()
    if config.public_profile is None:
        return GitHubAppUnavailable()
    if _runtime_fingerprint(config) != _attested_runtime_fingerprint:
        return GitHubAppUnavailable()
    if _public_fingerprint(config) != _attested_public_fingerprint:
        return GitHubAppUnavailable()
    return config.public_profile


def reset_github_app_public_attestation_for_tests() -> None:
    """Clear process-global state between isolated application tests."""
    global _attested_public_fingerprint, _attested_runtime_fingerprint
    _attested_runtime_fingerprint = None
    _attested_public_fingerprint = None


def _runtime_fingerprint(config: GitHubAppControlPlaneConfig) -> bytes:
    digest = hashlib.sha256()
    for value in (
        config.issuer,
        config.endpoint.base_url,
        config.private_key_pem,
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


def _public_fingerprint(config: GitHubAppControlPlaneConfig) -> bytes:
    profile = config.public_profile
    assert profile is not None
    digest = hashlib.sha256(_runtime_fingerprint(config))
    digest.update(profile.model_dump_json().encode("utf-8"))
    return digest.digest()


__all__ = [
    "attest_github_app_runtime_identity",
    "current_github_app_public_advertisement",
    "reset_github_app_public_attestation_for_tests",
]
