"""Harness / session substrate health-check bundle.

A registry slice carved out of :mod:`doctor_registry` so the parent file stays
under the 350-line authored-file limit. Two groups of harness-side checks live
here, in this order:

Group A — session/harness substrate (task 13):
  ``stale-sessions``, ``stale-session-reclaimer-alive``, ``session-startup-hook``,
  ``browser-substrate``, ``session-cwd-binding``.

Group B — harness substrate parity HCs (task 10):
  ``harness-substrate-drift``, ``codex-hook-matchers``, ``codex-hook-floor``,
  ``codex-hook-doc-drift``, ``apply-patch-deny-smoke``, ``apply-patch-observe-smoke``,
  ``codex-agent-adapter-drift``, ``codex-subagent-surface-truth``,
  ``path-claim-bash-guard``. The apply-patch HCs split from the hook bundle
  into ``doctor_hc_apply_patch`` to keep ``doctor_hc_codex_hooks`` under cap.

Public surface:

- :data:`HARNESS_HEALTH_CHECKS` — ordered list spliced into the parent
  registry's ``HEALTH_CHECKS``. Order is preserved so the doctor's report
  retains its existing top-down read.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_agents import (
    hc_browser_substrate,
    hc_session_startup_hook,
    hc_stale_reclaim_collision,
    hc_stale_session_reclaimer_alive,
    hc_stale_sessions,
)
from yoke_core.engines.doctor_hc_apply_patch import (
    hc_apply_patch_deny_smoke,
    hc_apply_patch_observe_smoke,
)
from yoke_core.engines.doctor_hc_codex_agent import (
    hc_codex_agent_adapter_drift,
    hc_codex_subagent_surface_truth,
)
from yoke_core.engines.doctor_hc_claim_boundary_audit import (
    hc_claim_boundary_audit,
)
from yoke_core.engines.doctor_hc_codex_hooks import (
    hc_codex_hook_doc_drift,
    hc_codex_hook_floor,
    hc_codex_hook_matchers,
)
from yoke_core.engines.doctor_hc_event_outcome_enum_coverage import (
    hc_event_outcome_enum_coverage,
)
from yoke_core.engines.doctor_hc_executor_canonicalization import (
    hc_executor_canonicalization,
)
from yoke_core.engines.doctor_hc_harness_substrate import (
    hc_harness_substrate_drift,
)
from yoke_core.engines.doctor_hc_install_bundle_drift import (
    hc_install_bundle_drift,
)
from yoke_core.engines.doctor_hc_path_claim_bash_guard import (
    hc_path_claim_bash_guard,
)
from yoke_core.engines.doctor_hc_reflection_capture_hook_coverage import (
    hc_reflection_capture_hook_coverage,
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
        "session-startup-hook",
        "Session startup hook",
        hc_session_startup_hook,
    ),
    HealthCheck(
        "browser-substrate",
        "Browser substrate health",
        hc_browser_substrate,
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
        "harness-substrate-drift",
        "All renderer outputs match canonical source",
        hc_harness_substrate_drift,
    ),
    HealthCheck(
        "codex-hook-matchers",
        "Codex hooks.json matchers cover required event/tool combos",
        hc_codex_hook_matchers,
    ),
    HealthCheck(
        "codex-hook-floor",
        "Operator Codex CLI meets manifest hook_enhanced floor",
        hc_codex_hook_floor,
    ),
    HealthCheck(
        "codex-hook-doc-drift",
        "Codex hook docs describe the current matcher set",
        hc_codex_hook_doc_drift,
    ),
    HealthCheck(
        "apply-patch-deny-smoke",
        "apply_patch deny smoke still passes offline",
        hc_apply_patch_deny_smoke,
    ),
    HealthCheck(
        "apply-patch-observe-smoke",
        "apply_patch events recorded with changed paths",
        hc_apply_patch_observe_smoke,
    ),
    HealthCheck(
        "codex-agent-adapter-drift",
        "Codex agent adapters match canonical bodies",
        hc_codex_agent_adapter_drift,
    ),
    HealthCheck(
        "codex-subagent-surface-truth",
        "Operator surface, manifests, and docs agree on conduct support",
        hc_codex_subagent_surface_truth,
    ),
    HealthCheck(
        "path-claim-bash-guard",
        "Path-claim Bash guard wired into rendered hook chains",
        hc_path_claim_bash_guard,
    ),
    HealthCheck(
        "install-bundle-drift",
        "Packaged install-bundle tree matches its source dirs",
        hc_install_bundle_drift,
    ),
    HealthCheck(
        "claim-boundary-audit",
        "Cross-session mutation evidence in the ledger",
        hc_claim_boundary_audit,
    ),
    HealthCheck(
        "event-outcome-enum-coverage",
        "Tool-call outcome enum coverage for HarnessToolCallDenied emitters",
        hc_event_outcome_enum_coverage,
    ),
    HealthCheck(
        "executor-canonicalization",
        "Active harness_sessions.executor values are canonical harness ids",
        hc_executor_canonicalization,
    ),
    HealthCheck(
        "reflection-capture-hook-coverage",
        "Every Agent-tool call in 24h emits ReflectionCaptureHookFired",
        hc_reflection_capture_hook_coverage,
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
