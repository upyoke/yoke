"""Shared vocabulary for item dependency edges."""

VALID_GATE_POINTS = frozenset({"activation", "integration", "closure", "coordination_only"})
VALID_SOURCES = frozenset(
    {"operator", "shepherd", "conduct", "feed", "migration", "idea", "refine"}
)

__all__ = ["VALID_GATE_POINTS", "VALID_SOURCES"]
