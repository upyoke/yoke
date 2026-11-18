"""Event-registry coverage health check.

Owns ``hc_event_registry_coverage`` — the HC that compares ``events``
against ``event_registry`` to surface stale registry entries (not
emitted in 30 days, excluding expected low-cadence events, and only once the
event history is older than that window) and rogue
events (emitted but not in the code catalog the registry mirrors).
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

#: Catalog events that are rare by design (failure, override and recovery
#: paths): a quiet 30-day window is not evidence they are stale.
EXPECTED_LOW_CADENCE: tuple[str, ...] = (
    "BranchProtectionCheckFailed",
    "BoardRebuildCommandFailed",
    "BrowserDaemonStartupFailed",
    "ChainEndDeferred",
    "DataLossDetected",
    "DeploymentRunFailed",
    "DeploymentRunStageFailed",
    "DispatcherDownstreamDegraded",
    "GateSatisfierRefused",
    "GitHubCloseFailure",
    "HarnessSessionResumeBlockShown",
    "HarnessToolCallStructuredExit",
    "HookExecutionFailed",
    "IdeaClaimHeld",
    "IdeaReadinessClaimCoverageRepairApplied",
    "IssueMigrated",
    "ItemMirrorAbsent",
    "ItemClaimReleaseRefused",
    "LeaseAcquired",
    "LeaseHeartbeated",
    "LeaseReleased",
    "MergePullRequestMergeRetried",
    "MergeQueueDriftCheckSkipped",
    "MergeTargetStale",
    "MergeVerificationFailed",
    "MigrationCompleted",
    "MigrationRolledBack",
    "OperatorLeaseRelease",
    "PathClaimBlockedReasonRefreshed",
    "PathIntegrityFailureDetected",
    "PathIntegrityRepairApplied",
    "PathTargetSymlinkSkipped",
    "PathTargetTentative",
    "PreviewEnvCleaned",
    "PreviewEnvCreated",
    "PreviewEnvOverwritten",
    "SMLRefreshCompleted",
    "SessionCwdBindingFailOpen",
    "SessionCwdBindingHealthCheckFailed",
    "SessionReactivationReacquiredClaims",
    "StrategyDocArchived",
    "StrategyDocUnarchived",
    "YokeFunctionPermissionDenied",
    "WorkHandedOff",
    "WorkflowGateAbsent",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_event_registry_coverage(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-event-registry-coverage: Event registry coverage."""
    if not _base._table_exists(conn, "event_registry"):
        rec.record(
            "HC-event-registry-coverage",
            "Event registry coverage",
            "PASS",
            "event_registry table not present, skipping",
        )
        return

    issues: List[str] = []

    # Stale: registered entries not emitted in 30 days, unless they are
    # expected low-cadence events. A universe whose event history is younger
    # than the window has had no chance to emit them, so it has no stale list.
    history = query_rows(
        conn,
        "SELECT 1 AS mature FROM events "
        f"WHERE created_at < {now_sql(offset_days=-30)} LIMIT 1",
    )
    stale = []
    if history:
        placeholders = ",".join(_p(conn) for _ in EXPECTED_LOW_CADENCE)
        stale = query_rows(
            conn,
            "SELECT er.event_name FROM event_registry er "
            f"WHERE er.event_name NOT IN ({placeholders}) "
            "AND er.event_name NOT IN ("
            "  SELECT DISTINCT ae.event_name FROM events ae "
            f"  WHERE ae.created_at >= {now_sql(offset_days=-30)}"
            ")",
            EXPECTED_LOW_CADENCE,
        )
    if stale:
        issues.append("Stale registry entries (not emitted in 30d):")
        for r in stale:
            issues.append(f"- {r['event_name']}")

    # Rogue: emitted in 30 days but not registered
    rogue = query_rows(
        conn,
        "SELECT DISTINCT ae.event_name FROM events ae "
        f"WHERE ae.created_at >= {now_sql(offset_days=-30)} "
        "AND ae.event_name NOT IN (SELECT event_name FROM event_registry)",
    )
    if rogue:
        issues.append("Rogue events (emitted but not registered):")
        for r in rogue:
            issues.append(f"- {r['event_name']}")

    if issues:
        rec.record(
            "HC-event-registry-coverage",
            "Event registry coverage",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record("HC-event-registry-coverage", "Event registry coverage", "PASS", "")
