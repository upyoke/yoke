"""Field comparison stage for resync detection."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from yoke_core.domain.actors import ActorError, actor_label_or_passthrough
from yoke_core.domain.lifecycle_predicates import TASK_TERMINAL_SUCCESS
from yoke_core.engines.resync_detect_compact_mirror import (
    COMPACT_MIRROR_FOOTER,  # noqa: F401 — re-exported for callers
    matches_compact_mirror as _matches_compact_mirror,
)
from yoke_core.engines.resync_detect_models import (
    DriftRecord,
    PairedItem,
    _get_label_value,
    normalize_body_for_compare,
)


def _row_to_dict(row) -> dict:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _render_actor_token(conn, value: str) -> str:
    """Render an `items.source` / `items.owner` value to a label token.

    Wraps :func:`actor_label_or_passthrough` so a missing-actor or
    missing-label condition does not abort the entire detect pass.
    Failure modes (orphan numeric id, missing label projection,
    minimal-schema test fixtures without the actors table) fall back
    to the raw column value so the comparator still produces a drift
    record naming the value the operator can investigate, rather than
    swallowing the row.
    """
    from yoke_core.domain import db_backend

    try:
        return actor_label_or_passthrough(conn, value)
    except ActorError:
        return value or ""
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass
        return value or ""


def stage2_compare(
    paired: List[PairedItem],
    gh_by_project: Dict[str, Dict[int, Dict]],
    heavy_by_project: Dict[str, Dict[int, Dict]],
    db_path: str,
) -> List[DriftRecord]:
    """Stage 2: compare local DB fields against GitHub issue fields."""
    from yoke_core.domain.db_helpers import connect

    conn = connect(db_path)

    # Prefetch items — body is rendered on demand
    items_by_id: Dict[int, Dict] = {}
    try:
        from yoke_core.domain.render_body import build_body
        cur = conn.execute(
            "SELECT id, title, status, priority, type, source, owner, frozen, blocked FROM items"
        )
        for row in cur.fetchall():
            d = _row_to_dict(row)
            d["body"] = build_body(conn, row["id"]) or ""
            d["source_label"] = _render_actor_token(conn, d.get("source") or "")
            d["owner_label"] = _render_actor_token(conn, d.get("owner") or "")
            items_by_id[row["id"]] = d
    except Exception:
        pass

    # Prefetch epic tasks
    epic_tasks_by_key: Dict[Tuple[Any, int], Dict] = {}
    try:
        cur = conn.execute(
            "SELECT epic_id, task_num, title, status, COALESCE(body, '') as body "
            "FROM epic_tasks"
        )
        for row in cur.fetchall():
            key = (row["epic_id"], row["task_num"])
            epic_tasks_by_key[key] = _row_to_dict(row)
    except Exception:
        pass

    conn.close()

    drifts: List[DriftRecord] = []

    for item in paired:
        proj = item.project or "yoke"
        proj_issues = gh_by_project.get(proj, {})
        gh_issue = proj_issues.get(item.gh_num)
        if not gh_issue:
            # Fallback: search all projects
            for p_issues in gh_by_project.values():
                if item.gh_num in p_issues:
                    gh_issue = p_issues[item.gh_num]
                    break
        if not gh_issue:
            continue

        if item.type == "backlog":
            id_num_str = item.id.replace("YOK-", "")
            try:
                id_num = int(id_num_str)
            except ValueError:
                continue

            local_item = items_by_id.get(id_num)
            if not local_item:
                continue

            # --- Title comparison ---
            local_title = local_item.get("title", "") or ""
            gh_title_raw = gh_issue.get("title", "")
            gh_title = re.sub(r"^\[YOK-\d+\]\s*", "", gh_title_raw)
            if gh_title and local_title != gh_title:
                drifts.append(DriftRecord(item.id, "title", local_title, gh_title))

            # --- Body comparison ---
            raw_local_body = local_item.get("body", "") or ""
            mirror_fields = {
                "title": local_item.get("title", "") or "",
                "project": proj,
                "status": local_item.get("status", "") or "",
                "type": local_item.get("type", "") or "",
            }
            gh_heavy = heavy_by_project.get(proj, {}).get(item.gh_num)
            if gh_heavy is not None:
                raw_gh_body = gh_heavy.get("body", "") or ""
                local_body = normalize_body_for_compare(raw_local_body)
                gh_body = normalize_body_for_compare(raw_gh_body)
                if local_body != gh_body and not _matches_compact_mirror(
                    local_body=raw_local_body,
                    gh_body=raw_gh_body,
                    item_fields=mirror_fields,
                    item_id=id_num,
                ):
                    drifts.append(DriftRecord(item.id, "body", "<local body>", "<github body>"))
            else:
                gh_light_body = gh_issue.get("body")
                if gh_light_body is not None:
                    raw_gh_light = gh_light_body or ""
                    local_body = normalize_body_for_compare(raw_local_body)
                    gh_body_light = normalize_body_for_compare(raw_gh_light)
                    if local_body != gh_body_light and not _matches_compact_mirror(
                        local_body=raw_local_body,
                        gh_body=raw_gh_light,
                        item_fields=mirror_fields,
                        item_id=id_num,
                    ):
                        drifts.append(DriftRecord(item.id, "body", "<local body>", "<github body>"))

            # --- Label comparison ---
            gh_labels = gh_issue.get("labels", [])

            local_status = local_item.get("status", "") or ""
            if local_status and local_status != "null":
                gh_status = _get_label_value(gh_labels, "status:")
                if local_status != gh_status:
                    drifts.append(DriftRecord(
                        item.id, "label-status",
                        f"status:{local_status}", f"status:{gh_status}",
                    ))

            local_priority = local_item.get("priority", "") or ""
            if local_priority and local_priority != "null":
                gh_priority = _get_label_value(gh_labels, "priority:")
                if local_priority != gh_priority:
                    drifts.append(DriftRecord(
                        item.id, "label-priority",
                        f"priority:{local_priority}", f"priority:{gh_priority}",
                    ))

            local_type = local_item.get("type", "") or ""
            if local_type and local_type != "null":
                gh_type = _get_label_value(gh_labels, "type:")
                if local_type != gh_type:
                    drifts.append(DriftRecord(
                        item.id, "label-type",
                        f"type:{local_type}", f"type:{gh_type}",
                    ))

            local_source_label = local_item.get("source_label", "") or ""
            if local_source_label:
                gh_source = _get_label_value(gh_labels, "source:")
                if local_source_label != gh_source:
                    drifts.append(DriftRecord(
                        item.id, "label-source",
                        f"source:{local_source_label}", f"source:{gh_source}",
                    ))

            local_owner_label = local_item.get("owner_label", "") or ""
            if local_owner_label:
                gh_owner = _get_label_value(gh_labels, "owner:")
                if local_owner_label != gh_owner:
                    drifts.append(DriftRecord(
                        item.id, "label-owner",
                        f"owner:{local_owner_label}", f"owner:{gh_owner}",
                    ))

            # Frozen label
            frozen_val = local_item.get("frozen", 0)
            local_frozen_bool = frozen_val in (1, "1", True, "true", "True")
            gh_has_frozen = any(lbl.get("name", "") == "frozen" for lbl in gh_labels)
            if local_frozen_bool and not gh_has_frozen:
                drifts.append(DriftRecord(item.id, "label-frozen", "frozen:true", "frozen:absent"))
            elif not local_frozen_bool and gh_has_frozen:
                drifts.append(DriftRecord(item.id, "label-frozen", "frozen:false", "frozen:present"))

            # blocked-flag label drift detection mirrors frozen
            blocked_val = local_item.get("blocked", 0)
            local_blocked_bool = blocked_val in (1, "1", True, "true", "True")
            gh_has_blocked = any(lbl.get("name", "") == "blocked" for lbl in gh_labels)
            if local_blocked_bool and not gh_has_blocked:
                drifts.append(DriftRecord(item.id, "label-blocked", "blocked:true", "blocked:absent"))
            elif not local_blocked_bool and gh_has_blocked:
                drifts.append(DriftRecord(item.id, "label-blocked", "blocked:false", "blocked:present"))

            # --- State comparison ---
            gh_state = gh_issue.get("state", "UNKNOWN")
            expected_state = "OPEN"
            if local_status in ("done", "release", "cancelled"):
                expected_state = "CLOSED"
            if gh_state != expected_state:
                drifts.append(DriftRecord(item.id, "state", expected_state, gh_state))

            # --- Comment presence check ---
            if local_status in ("done", "release") and gh_heavy is not None:
                comments = gh_heavy.get("comments", [])
                has_status = any(
                    "**Status:**" in c.get("body", "") for c in comments
                )
                if not has_status:
                    drifts.append(DriftRecord(
                        item.id, "comment", "has-status-comment", "missing",
                    ))

        elif item.type == "epic_task":
            file_path = item.file
            stripped = file_path.replace("epic_tasks:", "", 1)
            parts = stripped.rsplit("/", 1)
            if len(parts) != 2:
                continue
            raw_slug = parts[0]
            try:
                et_slug_int = int(raw_slug)
            except ValueError:
                et_slug_int = None
            try:
                et_num = int(parts[1])
            except ValueError:
                continue

            # Try both string and int key since epic_id may be stored as either
            local_task = epic_tasks_by_key.get((raw_slug, et_num))
            if local_task is None and et_slug_int is not None:
                local_task = epic_tasks_by_key.get((et_slug_int, et_num))
            if not local_task:
                continue

            # --- Title comparison ---
            local_task_title = local_task.get("title", "") or ""
            gh_title_raw = gh_issue.get("title", "")
            gh_title_norm = re.sub(r"^\[YOK-\d+\]\s*", "", gh_title_raw)
            gh_title_norm = re.sub(r"^Task\s+\d+:\s*", "", gh_title_norm)
            gh_title_norm = re.sub(r"^\d{3}\s+", "", gh_title_norm)

            if gh_title_raw and not re.match(r"^\[YOK-\d+\]", gh_title_raw):
                drifts.append(DriftRecord(item.id, "title", local_task_title, gh_title_raw))
            elif gh_title_norm and local_task_title and local_task_title != gh_title_norm:
                drifts.append(DriftRecord(item.id, "title", local_task_title, gh_title_raw))

            # --- State comparison ---
            task_status = local_task.get("status", "") or ""
            gh_state = gh_issue.get("state", "UNKNOWN")
            expected_state = "OPEN"
            if task_status in TASK_TERMINAL_SUCCESS or task_status == "cancelled":
                expected_state = "CLOSED"
            if gh_state != expected_state:
                drifts.append(DriftRecord(item.id, "state", expected_state, gh_state))

            # --- Body comparison ---
            local_task_body = normalize_body_for_compare(local_task.get("body", "") or "")
            gh_heavy = heavy_by_project.get(proj, {}).get(item.gh_num)
            if gh_heavy is not None:
                gh_task_body = normalize_body_for_compare(gh_heavy.get("body", "") or "")
                if local_task_body != gh_task_body:
                    drifts.append(DriftRecord(item.id, "body", "<local body>", "<github body>"))
            else:
                gh_light_body = gh_issue.get("body")
                if gh_light_body is not None:
                    gh_task_body_light = normalize_body_for_compare(gh_light_body or "")
                    if local_task_body != gh_task_body_light:
                        drifts.append(DriftRecord(item.id, "body", "<local body>", "<github body>"))

    return drifts
