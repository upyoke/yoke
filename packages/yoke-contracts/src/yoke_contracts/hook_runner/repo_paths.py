"""Portable repository identity for client facts and recorded lane paths."""

from __future__ import annotations


def normalize_repo_path(path: str) -> str:
    """Normalize separators, drive-letter case and trailing separators."""
    normalized = path.replace("\\", "/").rstrip("/")
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0].lower() + normalized[1:]
    return normalized or ("/" if path.startswith("/") else "")
