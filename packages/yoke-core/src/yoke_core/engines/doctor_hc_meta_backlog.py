"""Meta health checks — backlog quality and schema validation.

Extracted from ``doctor_hc_meta`` to keep that module under the file-line cap.
This sibling owns the backlog-quality and schema-validation HCs:

- ``hc_frontmatter_schema`` — backlog frontmatter schema validation.
- ``hc_title_length`` — configured per-project title-limit settings below
  the minimum.
- ``hc_backlog_quality`` — stale ideas, short titles, missing bodies.
- ``hc_items_needing_spec`` — items left with only their title.
- ``hc_epic_validation`` — per-epic DB validation (task numbering, statuses).

``doctor.py`` continues to import these symbols via ``doctor_hc_meta`` for
registration parity; this module is the authoritative source.
"""

from __future__ import annotations

import re
from datetime import timedelta
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from pathlib import Path
from typing import List

from yoke_contracts.title_policy import title_max_length_setting_error

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.item_spec_completeness import (
    item_needs_spec,
    needs_spec_reason,
)
from yoke_core.domain.item_workflow_validation import (
    invalid_item_workflow_stages,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.task_lifecycle import ALL_TASK_STATUSES

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_frontmatter_schema(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-frontmatter-schema: Backlog frontmatter schema validation.

    Deployment pipeline authority lives in ``items.deployment_flow`` and is
    checked by ``HC-invalid-item-flows``.
    """
    valid_priorities = {"high", "medium", "low"}
    issues = [
        f"- {render_item_ref(conn, item_id)}: invalid workflow stage "
        f"'{stage}' ({reason})"
        for item_id, stage, reason in invalid_item_workflow_stages(conn)
    ]
    rows = query_rows(
        conn,
        "SELECT id, priority, github_issue FROM items",
    )
    for row in rows:
        yok_id = render_item_ref(conn, row["id"])
        p = row["priority"]
        if p and p not in valid_priorities:
            issues.append(
                f"- {yok_id}: invalid priority '{p}' (expected: {' '.join(sorted(valid_priorities))})"
            )
        gh = row["github_issue"]
        if gh and gh != "null" and not re.match(r"^#\d+", gh):
            issues.append(f"- {yok_id}: github_issue '{gh}' does not match #N format")
    if issues:
        rec.record(
            "HC-frontmatter-schema",
            "Backlog frontmatter schema",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record("HC-frontmatter-schema", "Backlog frontmatter schema", "PASS", "")


def hc_title_length(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-title-length: a project's configured title limit below the minimum.

    Reuses the same validator the settings-save path enforces, so a stored
    value can only be flagged here by writing around that path (a direct
    DB edit, or a value stored before the minimum existed).
    """
    issues: List[str] = []
    for row in query_rows(conn, "SELECT id FROM projects ORDER BY id"):
        project_id = int(row["id"])
        configured = project_policy_value(conn, project_id, "title_max_length")
        if configured is None:
            continue
        error = title_max_length_setting_error(configured)
        if error:
            issues.append(f"- project {project_id}: {error}")

    if issues:
        rec.record(
            "HC-title-length", "Title length enforcement", "WARN", "\n".join(issues)
        )
    else:
        rec.record("HC-title-length", "Title length enforcement", "PASS", "")


def hc_backlog_quality(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-backlog-quality: Backlog quality (stale ideas, short titles, missing bodies)."""
    issues: List[str] = []
    fail_issues: List[str] = []
    now = _base.utc_now()

    # Read stale threshold from config
    stale_days = 30
    repo_root = _base._resolve_repo_root()
    if repo_root:
        cfg = Path(repo_root) / "data" / "config"
        if cfg.is_file():
            for line in cfg.read_text(errors="replace", encoding="utf-8").splitlines():
                if line.strip().startswith("backlog_stale_days="):
                    try:
                        stale_days = int(line.strip().split("=", 1)[1])
                    except ValueError:
                        pass
    stale_age = timedelta(days=stale_days)

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
        yok_id = render_item_ref(conn, row["id"])
        status = row["status"] or ""
        created = row["created_at"]
        title = row["title"] or ""
        priority = row["priority"]
        has_body = int(row["has_body"]) if row["has_body"] is not None else 0

        # Sub-check 1: Stale ideas
        if status == "idea":
            if created is None:
                issues.append(f"- {yok_id}: missing creation clock; idea age unknown")
            else:
                try:
                    age = now - parse_instant(created)
                except InvalidInstant:
                    issues.append(
                        f"- {yok_id}: invalid_instant — creation clock refused"
                    )
                else:
                    if age > stale_age:
                        issues.append(
                            f"- {yok_id}: stale idea ({age.days} days old, threshold: {stale_days})"
                        )

        # Sub-check 2: Title too short
        if title and len(title) < 10:
            issues.append(
                f'- {yok_id}: title too short ({len(title)} chars): "{title}"'
            )

        # Sub-check 3: Body-less items. Terminal exceptional states
        # (cancelled, rejected) never received a body and never will —
        # they are exempt from the body-required FAIL branch.
        if has_body == 0:
            if status == "idea":
                issues.append(
                    f"- {yok_id}: no body content (idea — add before advancing)"
                )
            elif status in ("cancelled", "rejected"):
                pass
            else:
                fail_issues.append(
                    f"- {yok_id}: no body content at status '{status}' — items past idea must have body"
                )

        # Sub-check 4: Missing priority
        if not priority or priority == "null":
            issues.append(f"- {yok_id}: missing priority")

    if fail_issues:
        all_issues = fail_issues + issues
        rec.record(
            "HC-backlog-quality", "Backlog quality", "FAIL", "\n".join(all_issues)
        )
    elif issues:
        rec.record("HC-backlog-quality", "Backlog quality", "WARN", "\n".join(issues))
    else:
        rec.record("HC-backlog-quality", "Backlog quality", "PASS", "")


def hc_items_needing_spec(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-items-needing-spec: items left with only their title.

    Every create now carries its spec, so these are leftovers from before
    that rule or from a session that stopped between two writes. The
    frontier holds each one labelled "Needs a spec"; this check lists them
    with the command that writes the spec or cancels the item.
    """
    from yoke_core.domain.workflow_runtime import load_workflow_runtime

    first_stages: dict = {}
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, title, spec, status, workflow_id, workflow_version_id "
        "FROM items ORDER BY id",
    )
    for row in rows:
        if not item_needs_spec(row):
            continue
        key = (row["workflow_id"], row["workflow_version_id"])
        if key not in first_stages:
            first_stages[key] = load_workflow_runtime(
                conn, workflow_id=key[0], workflow_version_id=int(key[1])
            ).stage_ids[0]
        if row["status"] != first_stages[key]:
            continue
        issues.append(f"- {needs_spec_reason(render_item_ref(conn, row['id']))}")

    rec.record(
        "HC-items-needing-spec",
        "Items that need a spec",
        "WARN" if issues else "PASS",
        "\n".join(issues),
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
            if t["status"] and t["status"] not in ALL_TASK_STATUSES:
                issues.append(
                    f"- {epic_id} task {t['task_num']}: invalid status '{t['status']}'"
                )

    if issues:
        rec.record(
            "HC-epic-validation", "Per-epic validation", "WARN", "\n".join(issues)
        )
    else:
        rec.record("HC-epic-validation", "Per-epic validation", "PASS", "")
