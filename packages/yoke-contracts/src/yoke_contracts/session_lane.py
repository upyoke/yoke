"""Frozen import surface for applied migration history entries.

Migration entries ``0054_remove_lane_allowlists`` and
``0055_remove_process_offer_settings`` import this module by name, and an
applied entry's bytes are pinned by its ledger digest, so the module must
keep answering exactly what those entries asked of it at the point in
history where they run — before ``0059_rename_session_lanes_to_levels``
renamed the stored ``lane_metadata`` key. Live code reads
:mod:`yoke_contracts.session_level`; nothing else may import this module.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.session_level import (
    LEGACY_LEVEL_PRESENTATION,
    retired_lane_setting_keys,
    retired_process_offer_keys,
)


def lane_presentation(
    lane: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """Resolve label/glyph metadata from the pre-rename ``lane_metadata`` key."""
    lane_name = str(lane or "")
    configured: Mapping[str, Any] = {}
    if isinstance(settings, Mapping):
        all_metadata = settings.get("lane_metadata")
        if isinstance(all_metadata, Mapping):
            candidate = all_metadata.get(lane_name)
            if isinstance(candidate, Mapping):
                configured = candidate
    fallback = LEGACY_LEVEL_PRESENTATION.get(lane_name, {})
    return {
        "label": str(configured.get("label") or lane_name),
        "glyph": str(configured.get("glyph") or fallback.get("glyph") or ""),
    }


__all__ = [
    "lane_presentation",
    "retired_lane_setting_keys",
    "retired_process_offer_keys",
]
