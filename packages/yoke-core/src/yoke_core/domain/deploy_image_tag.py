"""Canonical commit-derived image tags shared by deployment paths."""

from __future__ import annotations


CANONICAL_IMAGE_TAG_LENGTH = 12


def canonical_image_tag(commit: str) -> str:
    """Return the exact fixed-width image tag for a resolved commit."""
    normalized = str(commit or "").strip()
    if len(normalized) < CANONICAL_IMAGE_TAG_LENGTH:
        raise ValueError(
            "resolved commit is shorter than the canonical image tag length "
            f"({CANONICAL_IMAGE_TAG_LENGTH})"
        )
    return normalized[:CANONICAL_IMAGE_TAG_LENGTH]


__all__ = ["CANONICAL_IMAGE_TAG_LENGTH", "canonical_image_tag"]
