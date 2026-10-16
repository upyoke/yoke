"""Published Yoke server container image references.

Self-host deployments run the same server image the platform is built
from, published to GitHub Container Registry. Release images carry one
immutable tag derived from their source commit; bundles pin that tag so a
container restart cannot silently advance the running engine.
"""

from __future__ import annotations
from yoke_contracts.release_version import release_version

PUBLISHED_SERVER_IMAGE_REPOSITORY = "ghcr.io/upyoke/yoke-server"


def canonical_server_image_tag(version: str) -> str:
    """Use the release's identical commit-clock version as its image tag."""
    return release_version(version)


def pinned_server_image(version: str) -> str:
    """Return the published immutable image reference for *version*."""
    return f"{PUBLISHED_SERVER_IMAGE_REPOSITORY}:{canonical_server_image_tag(version)}"


__all__ = [
    "PUBLISHED_SERVER_IMAGE_REPOSITORY",
    "canonical_server_image_tag",
    "pinned_server_image",
]
