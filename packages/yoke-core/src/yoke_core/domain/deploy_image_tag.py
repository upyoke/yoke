"""Canonical commit-derived image tags shared by deployment paths."""

from __future__ import annotations

CANONICAL_IMAGE_TAG_LENGTH = 12


def canonical_image_tag(source_commit: str) -> str:
    """Generic project container builds use a fixed-width source identity."""
    normalized = str(source_commit or "").strip()
    if len(normalized) < CANONICAL_IMAGE_TAG_LENGTH:
        raise ValueError(
            "source commit is shorter than the canonical image tag length (12)"
        )
    return normalized[:CANONICAL_IMAGE_TAG_LENGTH]


__all__ = ["CANONICAL_IMAGE_TAG_LENGTH", "canonical_image_tag"]
