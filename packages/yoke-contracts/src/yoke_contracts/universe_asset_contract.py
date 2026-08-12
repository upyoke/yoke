"""Shared asset contract between the Yoke build and its universe host.

Artifact validation proves that publication bytes contain these assets. The
host's deployed smoke check remains the complementary proof that those bytes
are routed and served correctly; neither check replaces the other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseAsset:
    """One public universe asset and its required artifact marker."""

    public_path: str
    artifact_member: str
    marker: str


UNIVERSE_PUBLIC_ROOT = f"{chr(47)}universe"
UNIVERSE_ASSETS = (
    UniverseAsset(
        f"{UNIVERSE_PUBLIC_ROOT}/app.js",
        "yoke_core/ui/static/app.js",
        "mountUniverseApp",
    ),
    UniverseAsset(
        f"{UNIVERSE_PUBLIC_ROOT}/contract-version.js",
        "yoke_core/ui/static/contract-version.js",
        "UNIVERSE_APP_CONTRACT_VERSION",
    ),
    UniverseAsset(
        f"{UNIVERSE_PUBLIC_ROOT}/mount-options.js",
        "yoke_core/ui/static/mount-options.js",
        "validateMountRoot",
    ),
    UniverseAsset(
        f"{UNIVERSE_PUBLIC_ROOT}/shell.css",
        "yoke_core/ui/static/shell.css",
        "yoke-app-header",
    ),
)
