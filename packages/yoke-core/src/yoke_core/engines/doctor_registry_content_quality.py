"""Content-quality doctor HC bundle.

Sibling sub-registry that keeps `doctor_registry.py` under its 350-line cap.
Holds health checks that scan stored content — item content and stored
presentation values — for drift every project can be held to.

Per-project prose conventions (canon heading casing among them) are not facts
true of every project, so they live in each project's own `.yoke/doctor/`
folder and are discovered by `doctor_project_checks`. The stored-glyph check
belongs here because every project's board renders its stored glyphs.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_db_stored_glyphs import hc_stored_glyph_contract
from yoke_core.engines.doctor_registry_types import HealthCheck


CONTENT_QUALITY_HEALTH_CHECKS: List[HealthCheck] = [
    HealthCheck(
        "stored-glyph-contract",
        "Stored glyphs obey the glyph contract",
        hc_stored_glyph_contract,
    ),
]


__all__ = ["CONTENT_QUALITY_HEALTH_CHECKS"]
