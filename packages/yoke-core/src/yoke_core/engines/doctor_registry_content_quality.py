"""Content-quality doctor HC bundle.

Sibling sub-registry that keeps `doctor_registry.py` under its 350-line cap.
Holds health checks that scan item content (structured fields, sections) for
quality drift.

The bundle is currently empty: the content conventions checked so far — canon
heading casing among them — are per-project prose rules rather than facts true
of every project, so they live in each project's own `.yoke/doctor/` folder
and are discovered by `doctor_project_checks`. The bundle stays as the seam
for a content-quality rule the engine can assert for every project.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_registry_types import HealthCheck


CONTENT_QUALITY_HEALTH_CHECKS: List[HealthCheck] = [
]


__all__ = ["CONTENT_QUALITY_HEALTH_CHECKS"]
