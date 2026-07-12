"""Startup identity attestation and public GitHub App advertisement."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
import math
import threading
from typing import Any, Callable, Mapping

from yoke_contracts.github_app_public import (
    GitHubAppAdvertisement,
    GitHubAppPublicProfile,
    GitHubAppUnavailable,
)

from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfig,
    GitHubAppControlPlaneConfigError,
    has_github_app_runtime_configuration,
    load_github_app_control_plane_config,
    load_github_app_public_profile,
)
from yoke_core.domain.github_app_identity import validate_public_profile
from yoke_core.domain.github_app_identity_verification import (
    fetch_authenticated_app_identity,
)


@dataclass(frozen=True)
class _AttestationResult:
    configured: bool
    runtime_fingerprint: bytes | None = None
    public_fingerprint: bytes | None = None
    public_profile_failed: bool = False


GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS = 5.0

_log = logging.getLogger("yoke.api.startup")
_state_lock = threading.Lock()
_attestation_generation = 0
_attested_runtime_fingerprint: bytes | None = None
_attested_public_fingerprint: bytes | None = None


def attest_github_app_runtime_identity(
    env: Mapping[str, str] | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    identity_fetcher: Callable[..., Any] | None = None,
    timeout_seconds: float = GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS,
) -> bool:
    """Synchronously authenticate configured App authority once."""
    generation = _begin_attestation_attempt()
    result = _evaluate_attestation(
        env,
        opener=opener,
        identity_fetcher=identity_fetcher,
        timeout_seconds=timeout_seconds,
    )
    return _publish_attestation(result, generation=generation)


async def attest_github_app_runtime_identity_with_hard_deadline(
    env: Mapping[str, str] | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    identity_fetcher: Callable[..., Any] | None = None,
    timeout_seconds: float = GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS,
) -> bool:
    """Bound startup readiness even if DNS or response reads never finish."""
    generation = _begin_attestation_attempt()
    if not has_github_app_runtime_configuration(env):
        return False
    timeout = _hard_timeout_seconds(timeout_seconds)
    if timeout is None:
        _log.warning(
            "GitHub App runtime identity attestation deadline is invalid; "
            "startup continued without verified App authority"
        )
        return False

    loop = asyncio.get_running_loop()
    completed = loop.create_future()

    def deliver(result: _AttestationResult) -> None:
        if not completed.done():
            completed.set_result(result)

    def worker() -> None:
        result = _evaluate_attestation(
            env,
            opener=opener,
            identity_fetcher=identity_fetcher,
            timeout_seconds=timeout,
        )
        try:
            loop.call_soon_threadsafe(deliver, result)
        except RuntimeError:
            return

    threading.Thread(
        target=worker,
        name="yoke-github-app-startup-attestation",
        daemon=True,
    ).start()
    try:
        result = await asyncio.wait_for(completed, timeout=timeout)
    except asyncio.TimeoutError:
        _log.warning(
            "GitHub App runtime identity attestation exceeded its hard "
            "startup deadline; advertisement disabled"
        )
        return False
    return _publish_attestation(result, generation=generation)


def current_github_app_public_advertisement(
    env: Mapping[str, str] | None = None,
) -> GitHubAppAdvertisement:
    """Return the startup-attested profile without making a network request."""
    with _state_lock:
        runtime_fingerprint = _attested_runtime_fingerprint
        public_fingerprint = _attested_public_fingerprint
    if runtime_fingerprint is None or public_fingerprint is None:
        return GitHubAppUnavailable()
    try:
        config = load_github_app_control_plane_config(env)
    except GitHubAppControlPlaneConfigError:
        return GitHubAppUnavailable()
    if config.public_profile is None:
        return GitHubAppUnavailable()
    if _runtime_fingerprint(config) != runtime_fingerprint:
        return GitHubAppUnavailable()
    if _public_fingerprint(config) != public_fingerprint:
        return GitHubAppUnavailable()
    return config.public_profile


def reset_github_app_public_attestation_for_tests() -> None:
    """Clear process-global state and invalidate any late worker result."""
    _begin_attestation_attempt()


def _begin_attestation_attempt() -> int:
    global _attestation_generation
    global _attested_public_fingerprint, _attested_runtime_fingerprint
    with _state_lock:
        _attestation_generation += 1
        _attested_runtime_fingerprint = None
        _attested_public_fingerprint = None
        return _attestation_generation


def _evaluate_attestation(
    env: Mapping[str, str] | None,
    *,
    opener: Callable[..., Any] | None,
    identity_fetcher: Callable[..., Any] | None,
    timeout_seconds: float,
) -> _AttestationResult:
    if not has_github_app_runtime_configuration(env):
        return _AttestationResult(configured=False)
    public_profile_failed = False
    try:
        public_profile = load_github_app_public_profile(env, strict_partial=True)
    except GitHubAppControlPlaneConfigError:
        public_profile = None
        public_profile_failed = True
    try:
        config = load_github_app_control_plane_config(env)
        identity = (identity_fetcher or fetch_authenticated_app_identity)(
            config,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - caller publishes detail-free failure
        return _AttestationResult(
            configured=True,
            public_profile_failed=public_profile_failed,
        )

    public_fingerprint = None
    if public_profile is not None:
        try:
            validate_public_profile(identity, public_profile)
        except Exception:  # noqa: BLE001 - advertisement stays fail-closed
            public_profile_failed = True
        else:
            public_fingerprint = _public_fingerprint(
                config,
                profile=public_profile,
            )
    return _AttestationResult(
        configured=True,
        runtime_fingerprint=_runtime_fingerprint(config),
        public_fingerprint=public_fingerprint,
        public_profile_failed=public_profile_failed,
    )


def _publish_attestation(result: _AttestationResult, *, generation: int) -> bool:
    global _attested_public_fingerprint, _attested_runtime_fingerprint
    with _state_lock:
        if generation != _attestation_generation:
            return False
        _attested_runtime_fingerprint = result.runtime_fingerprint
        _attested_public_fingerprint = result.public_fingerprint
    if not result.configured:
        return False
    if result.public_profile_failed:
        _log.warning(
            "GitHub App public Connect profile is partial, invalid, or does not "
            "match authenticated App identity; set every public profile field "
            "consistently or unset all of them; advertisement disabled"
        )
    if result.runtime_fingerprint is None:
        _log.warning(
            "GitHub App runtime identity attestation failed; "
            "startup continued without verified App authority"
        )
        return False
    _log.info("GitHub App runtime identity attested")
    return True


def _hard_timeout_seconds(value: float) -> float | None:
    try:
        timeout = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return None
    return timeout


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


def _public_fingerprint(
    config: GitHubAppControlPlaneConfig,
    *,
    profile: GitHubAppPublicProfile | None = None,
) -> bytes:
    selected_profile = profile or config.public_profile
    assert selected_profile is not None
    digest = hashlib.sha256(_runtime_fingerprint(config))
    digest.update(selected_profile.model_dump_json().encode("utf-8"))
    return digest.digest()


__all__ = [
    "GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS",
    "attest_github_app_runtime_identity",
    "attest_github_app_runtime_identity_with_hard_deadline",
    "current_github_app_public_advertisement",
    "reset_github_app_public_attestation_for_tests",
]
