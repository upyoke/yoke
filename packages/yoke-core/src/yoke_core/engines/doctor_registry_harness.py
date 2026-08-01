"""Harness / session substrate health-check bundle.

A registry slice carved out of :mod:`doctor_registry` so the parent file stays
under the 350-line authored-file limit. Three groups of harness-side checks
live here, in this order:

Session/harness substrate:
  ``stale-sessions``, ``stale-session-reclaimer-alive``,
  ``stale-reclaim-collision``, ``session-cwd-binding``,
  ``session-pre-implementing-activity``, ``session-lane-mismatch``.

Ledger audit:
  ``claim-boundary-audit``.

Reflection capture:
  ``reflection-capture-unhandled``, ``reflection-capture-persist-failed``.

Checks that compare a project's *own* rendered adapters, hook wiring, or
packaged bundles against their sources are not engine checks — they belong to
the project that owns those sources, discovered from its ``.yoke/doctor/``
folder by :mod:`doctor_project_checks`.

Public surface:

- :data:`HARNESS_HEALTH_CHECKS` — ordered list spliced into the parent
  registry's ``HEALTH_CHECKS``. Order is preserved so the doctor's report
  retains its existing top-down read.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_agents_sessions import (
    hc_stale_reclaim_collision,
    hc_stale_session_reclaimer_alive,
    hc_stale_sessions,
)
from yoke_core.engines.doctor_hc_claim_boundary_audit import (
    hc_claim_boundary_audit,
)
from yoke_core.engines.doctor_hc_reflection_capture_hook_coverage import (
    hc_reflection_capture_unhandled,
)
from yoke_core.engines.doctor_hc_reflection_capture_persist_failed import (
    hc_reflection_capture_persist_failed,
)
from yoke_core.engines.doctor_hc_session_cwd_binding import (
    hc_session_cwd_binding,
    hc_session_pre_implementing_activity,
)
from yoke_core.engines.doctor_hc_session_lane_mismatch import (
    hc_session_lane_mismatch,
)
from yoke_core.engines.doctor_registry_types import HealthCheck


HARNESS_HEALTH_CHECKS: List[HealthCheck] = [
    # Group A — session/harness substrate (task 13)
    HealthCheck(
        "stale-sessions",
        "Stale session files",
        hc_stale_sessions,
    ),
    HealthCheck(
        "stale-session-reclaimer-alive",
        "Stale-session reclaimer alive",
        hc_stale_session_reclaimer_alive,
    ),
    HealthCheck(
        "stale-reclaim-collision",
        "Silent two-session reclaim collisions",
        hc_stale_reclaim_collision,
    ),
    HealthCheck(
        "session-cwd-binding",
        "Active session cwd matches bound worktree",
        hc_session_cwd_binding,
    ),
    HealthCheck(
        "session-pre-implementing-activity",
        (
            "Sessions must flip status to implementing before sustained "
            "tool-call activity"
        ),
        hc_session_pre_implementing_activity,
    ),
    HealthCheck(
        "session-lane-mismatch",
        "Session offer lane mismatch (envelope vs row)",
        hc_session_lane_mismatch,
    ),
    # Group B — harness substrate parity HCs (task 10)
    HealthCheck(
        "claim-boundary-audit",
        "Cross-session mutation evidence in the ledger",
        hc_claim_boundary_audit,
    ),
    HealthCheck(
        "reflection-capture-unhandled",
        "ReflectionCaptureHookUnhandled events in 24h need parser extension",
        hc_reflection_capture_unhandled,
    ),
    HealthCheck(
        "reflection-capture-persist-failed",
        "ReflectionCapturePersistFailed events in 24h (silent persist drops)",
        hc_reflection_capture_persist_failed,
    ),
]


__all__ = ["HARNESS_HEALTH_CHECKS"]
