"""Meta health checks — done-item run/deferral hygiene.

Extracted from ``doctor_hc_meta`` to keep that module under the file-line cap.
This sibling owns the post-done-state hygiene HCs:

- ``hc_undeployed_done`` — done items missing ``deployed_to`` on projects with flows.
- ``hc_orphaned_done_items`` — done items with worktree still set (bypass signal).
- ``hc_deferred_items`` — deferral language hygiene on done epics.

``doctor.py`` continues to import these symbols via ``doctor_hc_meta`` for
registration parity; this module is the authoritative source.
"""

from __future__ import annotations

import re
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_DEFERRED_ITEM_FIELDS = (
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
)


def _available_item_columns(conn) -> set[str]:
    if db_backend.connection_is_postgres(conn):
        rows = query_rows(
            conn,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'items'",
        )
        return {str(row["column_name"]) for row in rows}
    rows = query_rows(conn, "PRAGMA table_info(items)")
    return {str(row["name"]) for row in rows}


def _deferred_item_text(conn, row, fields: list[str]) -> str:
    chunks: list[str] = []
    for field in fields:
        value = row[field]
        if value is not None and str(value).strip() and str(value) != "null":
            chunks.append(str(value))
    if _base._table_exists(conn, "item_sections"):
        p = _p(conn)
        section_rows = query_rows(
            conn,
            f"SELECT section_name, content FROM item_sections "
            f"WHERE item_id = {p} ORDER BY ordering, section_name",
            (row["id"],),
        )
        for section in section_rows:
            content = section["content"]
            if content is not None and str(content).strip():
                chunks.append(f"## {section['section_name']}\n{content}")
    return "\n\n".join(chunks)


def hc_undeployed_done(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-undeployed-done: Undeployed done items."""
    issues: List[str] = []
    now = _base._now_epoch()
    # Default warn threshold: 7 days
    warn_seconds = 7 * 86400
    min_item_id = _base._read_int_cutoff("hc_undeployed_done_min_item_id")

    rows = query_rows(
        conn,
        "SELECT i.id, i.deployed_to, i.updated_at, i.project_id, "
        "COALESCE(p.slug, 'yoke') AS project "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE i.status='done'",
    )
    for row in rows:
        item_id = row["id"]
        if min_item_id is not None and item_id < min_item_id:
            continue
        deployed = row["deployed_to"]
        if deployed and deployed != "null":
            continue
        # Check if project has deployment envs (simplified: skip projects without flows)
        project = row["project"] or "yoke"
        if project == "null":
            project = "yoke"
        # For Python version, we check if deployment_flows exist for this project
        flow_count = query_scalar(
            conn,
            f"SELECT count(*) FROM deployment_flows WHERE project_id={_p(conn)}",
            (row["project_id"],),
        ) if _base._table_exists(conn, "deployment_flows") else 0
        if not flow_count or int(flow_count) == 0:
            continue

        updated = row["updated_at"]
        yok_id = f"YOK-{item_id}"
        if updated:
            upd_epoch = _base._iso_to_epoch(updated)
            if upd_epoch != 0:
                age_seconds = now - upd_epoch
                if age_seconds >= warn_seconds:
                    age_days = age_seconds // 86400
                    if age_days == 0:
                        age_hours = age_seconds // 3600
                        issues.append(f"- {yok_id}: done for {age_hours} hours with no deployed_to value")
                    else:
                        issues.append(f"- {yok_id}: done for {age_days} days with no deployed_to value")

    if issues:
        rec.record("HC-undeployed-done", "Undeployed done items", "WARN", "\n".join(issues))
    else:
        rec.record("HC-undeployed-done", "Undeployed done items", "PASS", "")


def hc_orphaned_done_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-done-items: Done items with signs of bypassed ceremony.

    DB-only portion: done items with worktree still set.
    (Branch check requires git and is deferred to a later task.)
    """
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, title, worktree FROM items "
        "WHERE status = 'done' "
        "AND worktree IS NOT NULL AND worktree <> '' AND worktree <> 'null' "
        "ORDER BY id",
    )
    for row in rows:
        issues.append(
            f"- YOK-{row['id']} ({row['title']}): worktree still set to '{row['worktree']}' "
            f"— ceremony may have been bypassed"
        )

    if issues:
        rec.record("HC-orphaned-done-items",
                    "Done items with signs of bypassed ceremony", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-orphaned-done-items",
                    "Done items with signs of bypassed ceremony", "PASS", "")


def hc_deferred_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-deferred-items: Deferred items enforcement for done epics."""
    issues: List[str] = []
    available = _available_item_columns(conn)
    fields = [field for field in _DEFERRED_ITEM_FIELDS if field in available]
    select_cols = ["id", *fields]
    rows = query_rows(
        conn,
        "SELECT "
        + ", ".join(select_cols)
        + " FROM items WHERE type='epic' AND status='done' ORDER BY id",
    )

    deferral_patterns = [
        re.compile(r"deferred to a follow-up", re.IGNORECASE),
        re.compile(r"deferred to follow-up", re.IGNORECASE),
        re.compile(r"isolated to a follow-up", re.IGNORECASE),
        re.compile(r"isolated to follow-up", re.IGNORECASE),
        re.compile(r"out of scope for this epic", re.IGNORECASE),
    ]

    for row in rows:
        body = _deferred_item_text(conn, row, fields)
        if not body:
            continue

        # Check for UNFILED in ## Deferred Items section
        in_section = False
        has_unfiled = False
        for line in body.splitlines():
            if line.startswith("## Deferred Items"):
                in_section = True
                continue
            if line.startswith("## ") and in_section:
                in_section = False
            if in_section and "unfiled" in line.lower():
                has_unfiled = True

        if has_unfiled:
            issues.append(f"- YOK-{row['id']}: has UNFILED entries in ## Deferred Items section")

        # Check for deferral language outside section without YOK-N references
        # Strip code blocks and the Deferred Items section
        stripped_lines = []
        in_fence = False
        in_deferred = False
        for line in body.splitlines():
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if line.startswith("## Deferred Items"):
                in_deferred = True
                continue
            if line.startswith("## "):
                in_deferred = False
            if not in_deferred:
                stripped_lines.append(line)

        stripped = "\n".join(stripped_lines)
        for pat in deferral_patterns:
            for match_line in stripped.splitlines():
                if pat.search(match_line) and "YOK-" not in match_line:
                    issues.append(
                        f"- YOK-{row['id']}: deferral language found in body without "
                        f"YOK-N reference or ## Deferred Items tracking"
                    )
                    break
            else:
                continue
            break

    if issues:
        rec.record("HC-deferred-items", "Deferred items enforcement (done epics)", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-deferred-items", "Deferred items enforcement (done epics)", "PASS", "")
