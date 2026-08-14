"""Canonical Progress Log section facts and entry formatting."""

from __future__ import annotations


PROGRESS_LOG_SECTION = "Progress Log"
PROGRESS_LOG_ORDERING = 200


def format_entry(*, timestamp: str, headline: str, body: str) -> str:
    """Format one timestamped Progress Log entry."""
    body_clean = body.rstrip("\n")
    return f"## {timestamp} entry — {headline.strip()}\n{body_clean}\n"


def join_entry(existing: str, entry: str) -> str:
    """Append an entry with at least one blank-line separator."""
    if not existing:
        return entry
    if existing.endswith("\n\n"):
        return existing + entry
    if existing.endswith("\n"):
        return existing + "\n" + entry
    return existing + "\n\n" + entry


__all__ = [
    "PROGRESS_LOG_ORDERING",
    "PROGRESS_LOG_SECTION",
    "format_entry",
    "join_entry",
]
