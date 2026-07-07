"""Events-ledger health checks — split into focused sibling modules.

The original monolithic events-ledger HC module exceeded the authored
350-line limit, so its checks were split into three focused siblings:

- ``doctor_hc_db_events_ledger`` — synthetic contamination, historical
  coverage collapse, and destructive maintenance audit.
- ``doctor_hc_db_events_registry`` — event registry coverage.
- ``doctor_hc_db_events_emission`` — emission rate plus stray-DB checks.

This module remains the canonical entry point that ``doctor.py`` and
external callers import. It re-exports the public HC functions owned by
the focused siblings.
"""

from __future__ import annotations

from yoke_core.engines.doctor_hc_db_events_emission import (
    hc_event_emission_rate,
    hc_stray_db,
)
from yoke_core.engines.doctor_hc_db_events_ledger import (
    hc_events_destructive_maintenance_audit,
    hc_events_historical_coverage_collapse,
    hc_events_synthetic_contamination,
)
from yoke_core.engines.doctor_hc_db_events_registry import (
    hc_event_registry_coverage,
)

__all__ = (
    "hc_events_synthetic_contamination",
    "hc_events_historical_coverage_collapse",
    "hc_events_destructive_maintenance_audit",
    "hc_event_registry_coverage",
    "hc_event_emission_rate",
    "hc_stray_db",
)
