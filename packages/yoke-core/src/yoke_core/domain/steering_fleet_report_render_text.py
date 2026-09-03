"""The formatting a fleet report's sections all share.

Kept apart from the sections themselves so a section rendered in its own
module still measures and caps its lines the same way every other one does.
"""

from __future__ import annotations


#: Longest list rendered per section; past this the steerer needs the board.
SECTION_LIMIT = 20

OVERDUE_MARK = "!"


def minutes(seconds: int) -> str:
    """Render one age at the coarsest unit that still says something."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def capped(lines: list[str], total: int) -> list[str]:
    """Close a section that ran past its limit by naming what it left out."""
    if total > SECTION_LIMIT:
        return [*lines, f"  ... {total - SECTION_LIMIT} more"]
    return lines


__all__ = ["OVERDUE_MARK", "SECTION_LIMIT", "capped", "minutes"]
