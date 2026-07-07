"""Backlog unsupported-field writer.

The shared mutation layer owns the standard item fields. This bridge
handles the small field set that still has direct validation rules:
``type``, ``source``, ``owner``, ``deploy_stage``, and
``architecture_impact`` (validated + normalized to its canonical enum
form so a stored value can never carry stray whitespace/case).
"""

from __future__ import annotations

from typing import Any, TextIO

from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.backlog_item_db_writes import _update_item_field
from yoke_core.domain.backlog_queries import LABEL_SYNC_FIELDS


def _apply_shell_fallback(
    conn: Any,
    item_id: int,
    field: str,
    value: str,
    out: TextIO,
) -> dict:
    """Handle fields outside the shared mutation surface."""
    if field == "type":
        if value not in ("epic", "issue"):
            return {"success": False, "error": "type must be 'epic' or 'issue'"}
    elif field in ("source", "owner"):
        if not value:
            return {"success": False, "error": f"{field} cannot be empty"}
    elif field == "deploy_stage":
        pass  # Freeform string
    elif field == "architecture_impact":
        # Normalize to the canonical enum form (strip/lowercase) and
        # reject unknown values, so this operator/repair surface can
        # never persist a stray-whitespace value that a downstream
        # comparison forgets to strip.
        from yoke_core.domain.architecture_impact import (
            ArchitectureImpactError,
            validate_value,
        )

        try:
            value = validate_value(value)
        except ArchitectureImpactError as exc:
            return {"success": False, "error": str(exc)}
    else:
        return {
            "success": False,
            "error": (
                f"field '{field}' is not supported by either the shared "
                "mutation layer or the unsupported-field write bridge."
            ),
        }

    _update_item_field(conn, item_id, field, value)
    print(f"Updated: YOK-{item_id} {field} -> {value}", file=out)

    if field in LABEL_SYNC_FIELDS:
        if not _rendering._sync_labels(item_id, out):
            _rendering._record_sync_failure(
                item_id, "labels", "sync_labels failed",
            )

    return {"success": True}


__all__ = ["_apply_shell_fallback"]
