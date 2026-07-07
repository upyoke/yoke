"""Meta health checks — backlog quality and schema validation.

Extracted from ``doctor_hc_meta`` to keep that module under the file-line cap.
This sibling owns the backlog-quality and schema-validation HCs:

- ``hc_frontmatter_schema`` — backlog frontmatter schema validation.
- ``hc_title_length`` — title length enforcement (items + epic tasks).
- ``hc_backlog_quality`` — stale ideas, short titles, missing bodies.
- ``hc_epic_validation`` — per-epic DB validation (task numbering, statuses).

``doctor.py`` continues to import these symbols via ``doctor_hc_meta`` for
registration parity; this module is the authoritative source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.idea_body_completeness import is_idea_body_incomplete
from yoke_core.domain.lifecycle import (
    ALL_ITEM_STATUSES,
    ALL_TASK_STATUSES,
    EXCEPTIONAL,
)

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

VALID_FRONTMATTER_FLOWS = {"accelerated", "full"}


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_frontmatter_schema(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-frontmatter-schema: Backlog frontmatter schema validation.

    ``items.flow`` is the historical intake speed field. Deployment
    pipeline authority lives in ``items.deployment_flow`` and is checked by
    ``HC-invalid-item-flows``.
    """
    valid_types = {"epic", "issue"}
    valid_priorities = {"high", "medium", "low"}
    valid_statuses = set(ALL_ITEM_STATUSES) | EXCEPTIONAL
    valid_flows = VALID_FRONTMATTER_FLOWS

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, type, status, priority, github_issue, flow, rework_count FROM items",
    )
    for row in rows:
        yok_id = f"YOK-{row['id']}"
        t = row["type"]
        if t and t not in valid_types:
            issues.append(f"- {yok_id}: invalid type '{t}' (expected: {' '.join(sorted(valid_types))})")
        s = row["status"]
        if s and s not in valid_statuses:
            issues.append(f"- {yok_id}: invalid status '{s}' (expected: {' '.join(sorted(valid_statuses))})")
        p = row["priority"]
        if p and p not in valid_priorities:
            issues.append(f"- {yok_id}: invalid priority '{p}' (expected: {' '.join(sorted(valid_priorities))})")
        gh = row["github_issue"]
        if gh and gh != "null" and not re.match(r"^#\d+", gh):
            issues.append(f"- {yok_id}: github_issue '{gh}' does not match #N format")
        fl = row["flow"]
        if fl and fl != "null" and fl not in valid_flows:
            alts = ", ".join(sorted(valid_flows)) if valid_flows else "(none registered)"
            issues.append(f"- {yok_id}: invalid flow '{fl}' (expected: {alts})")
        rw = row["rework_count"]
        if rw is not None and str(rw) != "null" and str(rw) != "":
            try:
                val = int(rw)
                if val < 0:
                    issues.append(f"- {yok_id}: rework_count '{rw}' is not a non-negative integer")
            except (ValueError, TypeError):
                issues.append(f"- {yok_id}: rework_count '{rw}' is not a non-negative integer")

    if issues:
        rec.record("HC-frontmatter-schema", "Backlog frontmatter schema", "WARN", "\n".join(issues))
    else:
        rec.record("HC-frontmatter-schema", "Backlog frontmatter schema", "PASS", "")


def hc_title_length(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-title-length: Title length check."""
    issues: List[str] = []

    # Items
    item_rows = query_rows(
        conn,
        "SELECT 'YOK-' || id || ' (' || length(title) || ' chars)' as label "
        "FROM items WHERE length(title) > 100 ORDER BY length(title) DESC",
    )
    if item_rows:
        count = len(item_rows)
        labels = "\n".join(r["label"] for r in item_rows)
        issues.append(f"{count} item(s) with titles >100 chars:\n{labels}")

    # Epic tasks
    task_rows = query_rows(
        conn,
        "SELECT 'Epic ' || epic_id || ' task ' || task_num || ' (' || length(title) || ' chars)' as label "
        "FROM epic_tasks WHERE length(title) > 100 ORDER BY length(title) DESC",
    )
    if task_rows:
        count = len(task_rows)
        labels = "\n".join(r["label"] for r in task_rows)
        issues.append(f"{count} epic task(s) with titles >100 chars:\n{labels}")

    if issues:
        rec.record("HC-title-length", "Title length enforcement", "WARN", "\n".join(issues))
    else:
        rec.record("HC-title-length", "Title length enforcement", "PASS", "")


def hc_backlog_quality(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-backlog-quality: Backlog quality (stale ideas, short titles, missing bodies)."""
    issues: List[str] = []
    fail_issues: List[str] = []
    now = _base._now_epoch()

    # Read stale threshold from config
    stale_days = 30
    repo_root = _base._resolve_repo_root()
    if repo_root:
        cfg = Path(repo_root) / "data" / "config"
        if cfg.is_file():
            for line in cfg.read_text(errors="replace").splitlines():
                if line.strip().startswith("backlog_stale_days="):
                    try:
                        stale_days = int(line.strip().split("=", 1)[1])
                    except ValueError:
                        pass
    stale_seconds = stale_days * 86400

    # body column retired. Check spec for meaningful content
    # beyond just the title heading (matching old has_body heuristic).
    rows = query_rows(
        conn,
        "SELECT id, status, created_at, title, priority, "
        "CASE WHEN spec IS NOT NULL AND TRIM(spec) <> '' "
        "     AND TRIM(spec) <> ('# ' || title) "
        "     THEN 1 ELSE 0 END AS has_body "
        "FROM items",
    )
    for row in rows:
        yok_id = f"YOK-{row['id']}"
        status = row["status"] or ""
        created = row["created_at"] or ""
        title = row["title"] or ""
        priority = row["priority"]
        has_body = int(row["has_body"]) if row["has_body"] is not None else 0

        # Sub-check 1: Stale ideas
        if status == "idea" and created:
            created_epoch = _base._iso_to_epoch(created)
            if created_epoch != 0:
                age = now - created_epoch
                if age > stale_seconds:
                    issues.append(f"- {yok_id}: stale idea ({age // 86400} days old, threshold: {stale_days})")

        # Sub-check 2: Title too short
        if title and len(title) < 10:
            issues.append(f"- {yok_id}: title too short ({len(title)} chars): \"{title}\"")

        # Sub-check 3: Body-less items. Terminal exceptional states
        # (cancelled, rejected) never received a body and never will —
        # they are exempt from the body-required FAIL branch.
        if has_body == 0:
            if status == "idea":
                issues.append(f"- {yok_id}: no body content (idea — add before advancing)")
            elif status in ("cancelled", "rejected"):
                pass
            else:
                fail_issues.append(f"- {yok_id}: no body content at status '{status}' — items past idea must have body")

        # Sub-check 4: Missing priority
        if not priority or priority == "null":
            issues.append(f"- {yok_id}: missing priority")

    if fail_issues:
        all_issues = fail_issues + issues
        rec.record("HC-backlog-quality", "Backlog quality", "FAIL", "\n".join(all_issues))
    elif issues:
        rec.record("HC-backlog-quality", "Backlog quality", "WARN", "\n".join(issues))
    else:
        rec.record("HC-backlog-quality", "Backlog quality", "PASS", "")


def hc_incomplete_idea_bodies(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-incomplete-idea-bodies: title-only idea bodies whose draft claim was reclaimed.

    Lists every ``status='idea'`` item whose body is title-only AND whose
    most recent work_claim was released with ``reason='reclaimed'`` (the
    stale-heartbeat eviction path). These are the items the operator
    needs to either rescue (re-run ``/yoke idea`` with the missing
    body) or ``/yoke freeze`` so they stop polluting the frontier.
    """
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, title, spec, created_at FROM items "
        "WHERE status = 'idea' ORDER BY id",
    )
    for row in rows:
        if not is_idea_body_incomplete(row):
            continue
        try:
            claim = conn.execute(
                "SELECT session_id, released_at FROM work_claims "
                f"WHERE target_kind = 'item' AND item_id = {_p(conn)} "
                "  AND release_reason = 'reclaimed' "
                "ORDER BY released_at DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
        except Exception:
            claim = None
        if claim is None:
            continue
        session_id = claim["session_id"] if hasattr(claim, "keys") else claim[0]
        released_at = claim["released_at"] if hasattr(claim, "keys") else claim[1]
        issues.append(
            f"- YOK-{row['id']}: incomplete idea body (created_at={row['created_at']}), "
            f"last_claim_session_id={session_id}, "
            f"claim_released_reason='reclaimed' (released_at={released_at})"
        )

    if issues:
        rec.record(
            "HC-incomplete-idea-bodies",
            "Incomplete idea bodies after stale-heartbeat reclaim",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-incomplete-idea-bodies",
            "Incomplete idea bodies after stale-heartbeat reclaim",
            "PASS",
            "",
        )


def hc_epic_validation(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-epic-validation: Per-epic validation (DB-only portion).

    The shell version calls validate.sh (filesystem). The Python version
    checks DB integrity for each epic: task numbering, status consistency.
    """
    issues: List[str] = []
    epic_ids = query_rows(
        conn,
        "SELECT DISTINCT epic_id FROM epic_tasks ORDER BY epic_id",
    )
    for row in epic_ids:
        epic_id = row["epic_id"]
        # Check for task_num gaps
        tasks = query_rows(
            conn,
            f"SELECT task_num, status FROM epic_tasks WHERE epic_id={_p(conn)} "
            "ORDER BY task_num",
            (epic_id,),
        )
        if not tasks:
            issues.append(f"- {epic_id}: no tasks found")
            continue
        # Check for duplicate task_num
        nums = [t["task_num"] for t in tasks]
        if len(nums) != len(set(nums)):
            issues.append(f"- {epic_id}: duplicate task numbers detected")
        # Check for invalid task statuses
        for t in tasks:
            if t["status"] and t["status"] not in ALL_TASK_STATUSES and t["status"] not in EXCEPTIONAL:
                issues.append(f"- {epic_id} task {t['task_num']}: invalid status '{t['status']}'")

    if issues:
        rec.record("HC-epic-validation", "Per-epic validation", "WARN", "\n".join(issues))
    else:
        rec.record("HC-epic-validation", "Per-epic validation", "PASS", "")
