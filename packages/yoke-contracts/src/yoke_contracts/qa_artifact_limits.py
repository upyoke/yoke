"""Shared transport limits for QA evidence artifacts."""

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_ARTIFACT_MANIFEST_BYTES = 64 * 1024 * 1024

__all__ = ["MAX_ARTIFACT_BYTES", "MAX_ARTIFACT_MANIFEST_BYTES"]
