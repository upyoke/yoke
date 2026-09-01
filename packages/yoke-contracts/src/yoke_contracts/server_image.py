"""Published Yoke server container image references.

Self-host deployments run the same server image the platform is built
from, published to GitHub Container Registry. Release images carry one
immutable tag derived from their source commit; bundles pin that tag so a
container restart cannot silently advance the running engine.
"""

from __future__ import annotations

PUBLISHED_SERVER_IMAGE_REPOSITORY = "ghcr.io/upyoke/yoke-server"
CANONICAL_IMAGE_TAG_LENGTH = 12


def canonical_server_image_tag(source_commit: str) -> str:
    """Return the fixed-width immutable image tag for a source commit."""
    normalized = str(source_commit or "").strip()
    if len(normalized) < CANONICAL_IMAGE_TAG_LENGTH:
        raise ValueError(
            "source commit is shorter than the canonical server image tag "
            f"length ({CANONICAL_IMAGE_TAG_LENGTH})"
        )
    return normalized[:CANONICAL_IMAGE_TAG_LENGTH]


def pinned_server_image(source_commit: str) -> str:
    """Return the published immutable image reference for *source_commit*."""
    return (
        f"{PUBLISHED_SERVER_IMAGE_REPOSITORY}:"
        f"{canonical_server_image_tag(source_commit)}"
    )


__all__ = [
    "CANONICAL_IMAGE_TAG_LENGTH",
    "PUBLISHED_SERVER_IMAGE_REPOSITORY",
    "canonical_server_image_tag",
    "pinned_server_image",
]
