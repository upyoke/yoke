"""Authoritative subject facts for lifecycle approval decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import CONFLICT_SURVEY_SECTION
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.item_json_sections import read_json_section
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def load_lifecycle_item(conn: Any, item_id: int) -> dict[str, Any]:
    """Load the item and workflow facts that define one transition snapshot."""
    row = conn.execute(
        "SELECT i.id, i.project_sequence, i.title, i.status, i.project_id, "
        "i.workflow_id, i.workflow_version_id, wv.version AS workflow_version, "
        "p.slug AS project, p.public_item_prefix, p.org_id "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        "LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id "
        f"WHERE i.id = {_p(conn)}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    return {key: row[key] for key in row.keys()}


def lifecycle_transition_matches(
    request: dict[str, Any],
    item: dict[str, Any],
    target: str,
    approval_source: Mapping[str, str],
) -> bool:
    """Return whether a request captures the current transition snapshot."""
    context = request.get("subject_context")
    if not isinstance(context, dict):
        return False
    return (
        str(context.get("from_stage") or "") == str(item["status"])
        and str(context.get("to_stage") or "") == target
        and str(context.get("workflow_id") or "") == str(item["workflow_id"])
        and int(context.get("workflow_version_id") or 0)
        == int(item["workflow_version_id"])
        and context.get("approval_source") == dict(approval_source)
        and request.get("consumed_at") is None
    )


def _branch_changes(conn: Any, item_id: int) -> dict[str, Any]:
    branch = ""
    commit_sha = ""
    if _table_exists(conn, "item_worktrees"):
        row = conn.execute(
            "SELECT branch, commit_sha FROM item_worktrees "
            f"WHERE item_id={_p(conn)} AND state='active' ORDER BY id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        if row is not None:
            branch = str(row[0] or "")
            commit_sha = str(row[1] or "")
    evidence = (
        read_json_section(
            conn,
            item_id=item_id,
            section=DASH_EVIDENCE_SECTION,
        )
        or {}
    )
    survey = (
        read_json_section(
            conn,
            item_id=item_id,
            section=CONFLICT_SURVEY_SECTION,
        )
        or {}
    )
    touched_files = list(
        evidence.get("touched_files") or survey.get("touch_paths") or ()
    )
    summary = str(evidence.get("result_summary") or "").strip()
    if not summary and touched_files:
        summary = f"{len(touched_files)} touched file(s) are recorded for the branch."
    elif not summary and branch:
        summary = "No touched files are recorded for the implementation branch."
    elif not summary:
        summary = "No implementation branch is recorded for this transition."
    return {
        "branch": branch or None,
        "commit_sha": commit_sha or None,
        "touched_files": touched_files,
        "summary": summary,
    }


def build_lifecycle_subject_context(
    conn: Any,
    item: dict[str, Any],
    target: str,
    approval_source: Mapping[str, str],
) -> dict[str, Any]:
    """Build decision-ready lifecycle facts from the locked item snapshot."""
    public_ref = format_item_ref(
        str(item["project"]),
        str(item["public_item_prefix"] or ""),
        int(item["project_sequence"]),
    )
    return {
        "item_id": int(item["id"]),
        "item_ref": public_ref,
        "title": f"{public_ref} — approve the {target} transition",
        "item_title": str(item["title"]),
        "from_stage": str(item["status"]),
        "to_stage": target,
        "workflow_id": str(item["workflow_id"]),
        "workflow_version_id": int(item["workflow_version_id"]),
        "branch_changes": _branch_changes(conn, int(item["id"])),
        "approval_source": dict(approval_source),
        # The approver reads the version a person can look up. The row id
        # this item pins is a different number, and naming it here sends
        # them to a version that does not exist.
        "policy_summary": (
            f"{item['workflow_id']}@{item.get('workflow_version') or '?'} · "
            f"{approval_source.get('entry') or ''}"
        ),
    }


__all__ = [
    "build_lifecycle_subject_context",
    "lifecycle_transition_matches",
    "load_lifecycle_item",
]
