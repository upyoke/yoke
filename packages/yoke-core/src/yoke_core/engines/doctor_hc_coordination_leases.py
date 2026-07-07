"""HC-coordination-leases: shared-operation lease liveness + audit provenance.

Two related signals on the governed shared-operation primitive:

* **Stale/orphan leases.** Active rows in ``coordination_leases`` whose
  ``heartbeat_at`` is older than the configured stale window OR whose owning
  ``harness_sessions`` row has ended_at set. Doctor reports them as a WARN —
  recovery still flows through the human-only operator-release surface.
* **Unmerged live-apply source.** Completed ``migration_audit`` rows whose
  ``source_branch`` is not an ancestor of ``integration_target`` (typically
  ``main``). A WARN if the worktree/branch was deleted before the change
  reached the integration target — the live schema mutation happened, the
  source commit did not survive merge.

Both checks self-skip cleanly on minimal-schema test fixtures, and they
never auto-release leases or rewrite audit rows. Surface only.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import yoke_core.engines.doctor_report as _base
from yoke_core.domain import db_backend
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_STALE_NAME = "HC-coordination-leases-stale-or-orphan"
_HC_STALE_DESC = "Stale/orphan shared-operation coordination leases"
_HC_UNMERGED_NAME = "HC-coordination-leases-unmerged-source"
_HC_UNMERGED_DESC = (
    "Completed live-apply audit rows whose source branch never reached "
    "the integration target"
)

_STALE_WINDOW_MIN = 60
_LIST_PREVIEW = 10


def hc_coordination_leases_stale_or_orphan(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Report active leases that look stale or orphaned."""
    if not _base._table_exists(conn, "coordination_leases"):
        rec.record(_HC_STALE_NAME, _HC_STALE_DESC, "PASS",
                   "coordination_leases table missing — skipping")
        return
    if not _base._column_exists(conn, "coordination_leases", "heartbeat_at"):
        rec.record(_HC_STALE_NAME, _HC_STALE_DESC, "PASS",
                   "heartbeat_at column missing — skipping")
        return

    threshold_iso = _iso_minutes_ago(_STALE_WINDOW_MIN)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT cl.id, cl.project_id, cl.lease_key, cl.session_id, "
        "cl.heartbeat_at, cl.acquired_at, hs.ended_at AS session_ended_at "
        "FROM coordination_leases AS cl "
        "LEFT JOIN harness_sessions AS hs ON hs.session_id = cl.session_id "
        "WHERE cl.released_at IS NULL "
        "  AND ( "
        "    cl.heartbeat_at IS NULL "
        f"    OR cl.heartbeat_at < {p} "
        "    OR hs.ended_at IS NOT NULL "
        "  ) "
        "ORDER BY COALESCE(cl.heartbeat_at, cl.acquired_at) ASC, cl.id ASC",
        (threshold_iso,),
    ).fetchall()

    if not rows:
        rec.record(_HC_STALE_NAME, _HC_STALE_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(rows)} active lease(s) look stale or orphaned "
        f"(heartbeat_at older than {_STALE_WINDOW_MIN}m or owning session ended). "
        "Recovery is operator-driven: "
        "`python3 -m yoke_core.api.service_client coordination-lease-release "
        "--project P --key K --reason '...'`."
    ]
    for row in rows[:_LIST_PREVIEW]:
        reason = (
            "session ended" if row["session_ended_at"] else
            ("no heartbeat" if row["heartbeat_at"] is None else "heartbeat stale")
        )
        issues.append(
            f"  - id={row['id']} project={row['project_id']} "
            f"key={row['lease_key']} session={row['session_id']} "
            f"heartbeat_at={row['heartbeat_at']} ({reason})"
        )
    if len(rows) > _LIST_PREVIEW:
        issues.append(f"  ... and {len(rows) - _LIST_PREVIEW} more")
    issues.append(
        "- Inspect via: `python3 -m yoke_core.api.service_client "
        "coordination-lease-list --active-only`"
    )

    rec.record(_HC_STALE_NAME, _HC_STALE_DESC, "WARN", "\n".join(issues))


def hc_coordination_leases_unmerged_source(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Report completed live-apply audit rows whose source branch never merged."""
    if not _base._table_exists(conn, "migration_audit"):
        rec.record(_HC_UNMERGED_NAME, _HC_UNMERGED_DESC, "PASS",
                   "migration_audit table missing — skipping")
        return
    required = ("source_branch", "integration_target", "worktree")
    for column in required:
        if not _base._column_exists(conn, "migration_audit", column):
            rec.record(_HC_UNMERGED_NAME, _HC_UNMERGED_DESC, "PASS",
                       f"{column} column missing — skipping")
            return

    rows = conn.execute(
        "SELECT id, migration_name, source_branch, source_commit, "
        "integration_target, worktree, completed_at "
        "FROM migration_audit "
        "WHERE state = 'completed' "
        "  AND source_branch IS NOT NULL "
        "  AND integration_target IS NOT NULL "
        "ORDER BY id DESC"
    ).fetchall()

    unmerged: List[dict] = []
    for row in rows:
        if not _branch_merged(
            worktree=row["worktree"],
            source_branch=row["source_branch"],
            source_commit=row["source_commit"],
            integration_target=row["integration_target"],
        ):
            unmerged.append(dict(row))

    if not unmerged:
        rec.record(_HC_UNMERGED_NAME, _HC_UNMERGED_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(unmerged)} completed live-apply audit row(s) whose source "
        "branch is not an ancestor of integration_target. The schema "
        "mutation landed on the authoritative DB, but the source commit "
        "did not survive merge — investigate whether the worktree was "
        "deleted before the slice merged."
    ]
    for row in unmerged[:_LIST_PREVIEW]:
        issues.append(
            f"  - audit_id={row['id']} module={row['migration_name']} "
            f"source_branch={row['source_branch']} "
            f"integration_target={row['integration_target']}"
        )
    if len(unmerged) > _LIST_PREVIEW:
        issues.append(f"  ... and {len(unmerged) - _LIST_PREVIEW} more")
    issues.append(
        "- Inspect via: `python3 -m yoke_core.cli.db_router query "
        "\"SELECT id, migration_name, source_branch, source_commit, "
        "integration_target FROM migration_audit WHERE state='completed'\"`"
    )

    rec.record(_HC_UNMERGED_NAME, _HC_UNMERGED_DESC, "WARN", "\n".join(issues))


def _iso_minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch_merged(
    *,
    worktree: Optional[str],
    source_branch: Optional[str],
    source_commit: Optional[str],
    integration_target: Optional[str],
) -> bool:
    """Return True when the source ref is an ancestor of ``integration_target``.

    Prefer ``source_commit`` because branches can be deleted after a live
    apply. Best-effort: when the repo path is missing or git refuses to answer
    for infrastructure reasons, treat the row as merged so the HC does not
    spam WARNs on a host that has rotated the working tree away.
    """
    source_ref = source_commit or source_branch
    if not source_ref or not integration_target:
        return True
    repo = worktree or "."
    try:
        result = subprocess.run(
            ["git", "-C", repo, "merge-base", "--is-ancestor",
             source_ref, integration_target],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True
    if result.returncode == 0:
        return True
    # Exit 1 is the canonical "not an ancestor" answer. Any other non-zero
    # (most commonly 128: not a git repo / unknown ref / worktree gone) is
    # treated as merged so a rotated tree does not spam WARNs.
    return result.returncode != 1


__all__ = [
    "hc_coordination_leases_stale_or_orphan",
    "hc_coordination_leases_unmerged_source",
]
