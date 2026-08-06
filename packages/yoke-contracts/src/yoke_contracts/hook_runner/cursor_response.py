"""Cursor allow-response requirements shared by every hook exit path."""

from __future__ import annotations


CURSOR_LIFECYCLE_EVENTS = frozenset({"Stop", "SessionEnd"})


def cursor_lifecycle_allow_stdout(
    event_name: str, preserved_stdout: str = "",
) -> str:
    """Keep existing stdout or supply Cursor's required lifecycle object."""
    if preserved_stdout:
        return preserved_stdout
    return "{}" if event_name in CURSOR_LIFECYCLE_EVENTS else ""


__all__ = ["CURSOR_LIFECYCLE_EVENTS", "cursor_lifecycle_allow_stdout"]
