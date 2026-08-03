"""Read definition-owned lifecycle-stage display metadata."""

from __future__ import annotations

import json
from typing import Optional


def workflow_definition(raw: object) -> Optional[dict]:
    """Decode one stored workflow definition, returning ``None`` on drift."""
    if isinstance(raw, dict):
        return raw
    if raw in (None, ""):
        return None
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def stage_glyph(
    definition: Optional[dict],
    status: str,
) -> Optional[str]:
    """Return a stage glyph when the pinned definition declares one."""
    if definition is None:
        return None
    for stage in definition.get("stages") or ():
        if not isinstance(stage, dict) or str(stage.get("id")) != status:
            continue
        glyph = stage.get("glyph")
        return str(glyph) if glyph else None
    return None


__all__ = ["stage_glyph", "workflow_definition"]
