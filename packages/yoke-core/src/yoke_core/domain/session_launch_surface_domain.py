"""Closed launch-surface vocabulary shared by schema and migrations."""

from __future__ import annotations

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS


LAUNCH_SURFACES = tuple(sorted(KNOWN_SURFACE_LABELS))
LAUNCH_SURFACE_VALUES_SQL = ", ".join(f"'{surface}'" for surface in LAUNCH_SURFACES)
REQUESTED_SURFACE_COLUMN_DDL = (
    f"TEXT NOT NULL CHECK(requested_surface IN ({LAUNCH_SURFACE_VALUES_SQL}))"
)
SELECTED_SURFACE_COLUMN_DDL = (
    f"TEXT NOT NULL CHECK(selected_surface IN ({LAUNCH_SURFACE_VALUES_SQL}))"
)


__all__ = [
    "LAUNCH_SURFACES",
    "LAUNCH_SURFACE_VALUES_SQL",
    "REQUESTED_SURFACE_COLUMN_DDL",
    "SELECTED_SURFACE_COLUMN_DDL",
]
