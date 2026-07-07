"""Published Yoke server container image reference.

Self-host deployments run the same server image the platform is built
from, published to GitHub Container Registry. This module is the single
source for the default published reference — the self-host bundle's
``.env`` writer and the self-host docs read it from here, mirroring how
hosted endpoint constants live only in :mod:`yoke_contracts.api_urls`.
"""

from __future__ import annotations

PUBLISHED_SERVER_IMAGE_REPOSITORY = "ghcr.io/upyoke/yoke-server"
DEFAULT_SERVER_IMAGE = f"{PUBLISHED_SERVER_IMAGE_REPOSITORY}:latest"

__all__ = ["DEFAULT_SERVER_IMAGE", "PUBLISHED_SERVER_IMAGE_REPOSITORY"]
