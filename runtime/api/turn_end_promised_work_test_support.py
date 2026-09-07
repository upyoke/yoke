"""Shared fakes for the turn-end promised-work gate's two test modules.

The gate's decision routing and its hold ceiling are asserted
separately and must be asserted against the same world, so the
connection stand-in and the fixed clock both live here rather than
being copied into each module.
"""

from __future__ import annotations

from datetime import datetime, timezone


class _Conn:
    """A connection that records the statements the gate runs through it."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> "_Conn":
        self.statements.append((query, params))
        return self

    def fetchone(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        return None


#: One fixed instant, so a cooldown boundary is exact rather than racy.
_NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


__all__ = ["_NOW", "_Conn"]
