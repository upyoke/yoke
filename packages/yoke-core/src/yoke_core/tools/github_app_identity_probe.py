"""Verify the core container's mounted GitHub App key without exposing it."""

from __future__ import annotations

import os
import sys

from yoke_core.domain.github_app_control_plane import (
    load_github_app_control_plane_config,
    load_github_app_public_profile,
)
from yoke_core.domain.github_app_identity import validate_public_profile
from yoke_core.domain.github_app_identity_verification import (
    fetch_authenticated_app_identity,
)


def verify_mounted_identity() -> None:
    """Sign and call ``GET /app`` using only container-mounted authority."""
    profile = load_github_app_public_profile(os.environ, strict_partial=True)
    config = load_github_app_control_plane_config()
    identity = fetch_authenticated_app_identity(
        config,
        timeout_seconds=30.0,
    )
    if profile is not None:
        validate_public_profile(identity, profile)


def main() -> int:
    try:
        verify_mounted_identity()
    except Exception:
        print("GitHub App identity verification failed", file=sys.stderr)
        return 1
    print("GitHub App identity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "verify_mounted_identity"]
