"""Canonical commit-derived image tags shared by deployment paths."""

from __future__ import annotations

from yoke_contracts.server_image import (
    CANONICAL_IMAGE_TAG_LENGTH,
    canonical_server_image_tag,
)

canonical_image_tag = canonical_server_image_tag


__all__ = ["CANONICAL_IMAGE_TAG_LENGTH", "canonical_image_tag"]
