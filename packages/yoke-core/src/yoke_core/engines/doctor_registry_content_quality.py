"""Content-quality doctor HC bundle.

Sibling sub-registry that keeps `doctor_registry.py` under its 350-line cap.
Holds health checks that scan item content (structured fields, sections) for
quality drift such as off-canon heading casing.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_board_emoji_universality import (
    hc_board_emoji_universality,
)
from yoke_core.engines.doctor_hc_events_app_state_reads import (
    hc_events_app_state_reads,
)
from yoke_core.engines.doctor_hc_fallback_registry_coherence import (
    hc_fallback_registry_coherence,
)
from yoke_core.engines.doctor_hc_heading_casing import hc_heading_casing_canon
from yoke_core.engines.doctor_hc_field_note_coherence import (
    HC_DESC as FIELD_NOTE_COHERENCE_DESC,
    hc_field_note_coherence,
)
from yoke_core.engines.doctor_hc_skill_recipe_execution import (
    hc_skill_recipe_execution,
)
from yoke_core.engines.doctor_registry_types import HealthCheck


CONTENT_QUALITY_HEALTH_CHECKS: List[HealthCheck] = [
    HealthCheck(
        "heading-casing-canon",
        "Canonical heading casing across item structured fields and sections",
        hc_heading_casing_canon,
    ),
    HealthCheck(
        "skill-recipe-execution",
        "Skill-body yoke CLI recipes smoke-dispatch cleanly",
        hc_skill_recipe_execution,
    ),
    HealthCheck(
        "fallback-registry-coherence",
        "yoke_operation_inventory matches function + CLI registries",
        hc_fallback_registry_coherence,
    ),
    HealthCheck(
        "field-note-coherence",
        FIELD_NOTE_COHERENCE_DESC,
        hc_field_note_coherence,
    ),
    HealthCheck(
        "events-app-state-reads",
        "Events table reads outside telemetry allowlist",
        hc_events_app_state_reads,
    ),
    HealthCheck(
        "board-emoji-universality",
        "Board emoji render universally (no VS16/skin-tone)",
        hc_board_emoji_universality,
    ),
]


__all__ = ["CONTENT_QUALITY_HEALTH_CHECKS"]
