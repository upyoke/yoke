"""Meta health checks — epic lifecycle.

Cluster: HC checks anchored on the ``items`` table for epic-lifecycle
state (orphaned active items, premature done, shepherd spec integrity,
stale body, simulation evidence on reviewed epics, and missing
deployment_flow assignments).

HC functions: HC-orphaned-active-items, HC-premature-done,
HC-shepherd-spec-integrity, HC-stale-body,
HC-reviewed-implementation-epics-no-sim, HC-missing-flow
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_orphaned_active_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-active-items: Orphaned active items (merged code, non-done status)."""
    repo_root = _base._resolve_repo_root()
    issues: List[str] = []
    flagged: set = set()

    # Check items with merged_at set but status not done/cancelled
    rows = query_rows(
        conn,
        "SELECT id, status, COALESCE(worktree, '') as worktree "
        "FROM items WHERE merged_at IS NOT NULL AND merged_at <> '' "
        "AND status NOT IN ('done', 'cancelled') ORDER BY id",
    )
    for row in rows:
        item_id = row["id"]
        if item_id in flagged:
            continue
        flagged.add(item_id)
        issues.append(
            f"- YOK-{item_id} (status: {row['status']}): merged_at is set but status is not done. "
            f"Run: `/yoke usher YOK-{item_id}` to complete the done transition."
        )

    # Check items with worktree branch merged into main
    if repo_root:
        main_branch = "main"
        r = _base._run(["git", "-C", repo_root, "rev-parse", "--verify", "main"], timeout=5)
        if r.returncode != 0:
            r2 = _base._run(["git", "-C", repo_root, "rev-parse", "--verify", "master"], timeout=5)
            if r2.returncode == 0:
                main_branch = "master"

        wt_rows = query_rows(
            conn,
            "SELECT id, status, worktree FROM items "
            "WHERE status IN ('planned','implementing','reviewing-implementation',"
            "'reviewed-implementation','polishing-implementation','release','implemented') "
            "AND worktree IS NOT NULL AND worktree <> '' ORDER BY id",
        )
        for row in wt_rows:
            item_id = row["id"]
            if item_id in flagged:
                continue
            wt = row["worktree"]
            # Check if branch is ancestor of main
            r = _base._run(["git", "-C", repo_root, "merge-base", "--is-ancestor", wt, main_branch],
                      timeout=5)
            if r.returncode == 0:
                flagged.add(item_id)
                issues.append(
                    f"- YOK-{item_id} (status: {row['status']}): branch '{wt}' is merged to {main_branch}. "
                    f"Run: `/yoke usher YOK-{item_id}` to complete the done transition."
                )

    if issues:
        rec.record("HC-orphaned-active-items", "Orphaned active items", "WARN", "\n".join(issues))
    else:
        rec.record("HC-orphaned-active-items", "Orphaned active items", "PASS", "")



def hc_premature_done(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-premature-done: Items at done without merged_at."""
    min_item_id = _base._read_int_cutoff("hc_premature_done_min_item_id")
    rows = query_rows(
        conn,
        "SELECT id, type, title, COALESCE(merged_at, '') as merged_at "
        "FROM items WHERE status = 'done' "
        "AND (merged_at IS NULL OR merged_at = '') ORDER BY id",
    )
    issues = [
        f"- YOK-{r['id']} ({r['type']}: {r['title']}): status=done but merged_at is null"
        for r in rows if min_item_id is None or r["id"] >= min_item_id
    ]

    if issues:
        rec.record("HC-premature-done", "Done items without merged_at", "WARN", "\n".join(issues))
    else:
        rec.record("HC-premature-done", "Done items without merged_at", "PASS", "")



def hc_shepherd_spec_integrity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-shepherd-spec-integrity: Shepherd spec body integrity."""
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, spec, design_spec, technical_plan FROM items "
        "WHERE type='epic' AND status NOT IN ('idea','cancelled') "
        "ORDER BY id",
    )
    for row in rows:
        item_id = row["id"]
        # Check for epics past idea without specs
        if not row["spec"] and not row["design_spec"] and not row["technical_plan"]:
            issues.append(f"- YOK-{item_id}: epic past idea status but has no spec/design_spec/technical_plan")

    if issues:
        rec.record("HC-shepherd-spec-integrity", "Shepherd spec body integrity", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-shepherd-spec-integrity", "Shepherd spec body integrity", "PASS", "")



def hc_stale_body(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-body: Retired. Body cache columns no longer exist."""
    rec.record("HC-stale-body", "Stale body (retired)", "PASS", "Retired — body is rendered on demand")



def hc_reviewed_implementation_epics_no_sim(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-reviewed-implementation-epics-no-sim: Reviewed epics without integration simulation."""
    if not _base._table_exists(conn, "qa_runs") or not _base._table_exists(conn, "qa_requirements"):
        rec.record(
            "HC-reviewed-implementation-epics-no-sim",
            "Reviewed-implementation epics without simulation",
            "PASS",
            "",
        )
        return

    rows = query_rows(
        conn,
        "SELECT i.id FROM items i "
        "WHERE i.type = 'epic' AND i.status = 'reviewed-implementation' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM qa_runs qr "
        "  JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id "
        "  WHERE qreq.qa_kind = 'simulation' "
        # both items.id and qa_requirements.item_id are INTEGER; compare
        # directly so the predicate is portable (PG rejects integer = text)
        "    AND qreq.item_id = i.id "
        # deliberate case-sensitive match against internal JSON-literal phase token
        "    AND qreq.success_policy LIKE '%%\"phase\":\"integration\"%%'"
        ") ORDER BY i.id",
    )

    issues = [
        f"- YOK-{r['id']}: status is 'reviewed-implementation' but no integration simulation record exists"
        for r in rows
    ]

    if issues:
        rec.record(
            "HC-reviewed-implementation-epics-no-sim",
            "Reviewed-implementation epics without simulation",
            "FAIL",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-reviewed-implementation-epics-no-sim",
            "Reviewed-implementation epics without simulation",
            "PASS",
            "",
        )



def hc_missing_flow(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-missing-flow: non-terminal items without deployment_flow."""
    if not _base._column_exists(conn, "items", "deployment_flow"):
        rec.record("HC-missing-flow", "Items without deployment flow", "PASS",
                    "deployment_flow column does not exist yet — skipping")
        return

    # blocked is now a flag; the legacy 'blocked' status survives
    # only as drift (HC-blocked-status-drift owns it). Exclude blocked-flag
    # rows via the canonical flag check.
    rows = query_rows(
        conn,
        "SELECT i.id, i.status, p.slug AS project FROM items i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE (i.blocked IS NULL OR i.blocked = 0) "
        "AND i.status NOT IN ('done', 'wontdo', 'cancelled', 'stopped', 'failed') "
        "AND (i.deployment_flow IS NULL OR i.deployment_flow = '') "
        "ORDER BY i.id",
    )
    issues = [
        f"- YOK-{r['id']} (status: {r['status']}, project: {r['project'] or 'null'}): no deployment_flow"
        for r in rows
    ]

    if issues:
        rec.record("HC-missing-flow", "Items without deployment flow", "WARN", "\n".join(issues))
    else:
        rec.record("HC-missing-flow", "Items without deployment flow", "PASS", "")
