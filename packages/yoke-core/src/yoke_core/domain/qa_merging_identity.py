"""Which trees a merge proved, for the item that merge landed.

The terminal QA gate refuses an item whose blocking proof does not cover the
tree that landed. That comparison needs the landed tree's identity, and one
merge legitimately produces more than one: the lane head that entered the
merge, which the item's own cases ran against, and the integrated head the
merge gate validated, which carries the lane plus whatever the base branch or
the merge-queue train brought with it. Under a merge queue the two can never
coincide — the train's combined head is a commit no single member ever ran
against — so demanding one SHA satisfy every requirement strands every
queue-landed item at its terminal transition.

So the accepted set is what the merge boundary itself recorded: the receipt it
writes as it lands, the newest CI head it proved green, and the execution
evidence a workflow may add on top. A run recorded at none of those predates
the merge and is still refused.

Rationale and rejected alternatives: ``docs/archive/decisions/
merge-close-out-completion.md``.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists

# How far back to read this item's merge receipts. One merge writes a
# pre-merge row and a completion row; the window covers repeated retries
# while still folding newest-first, so a superseded attempt never outranks
# the identity the latest attempt recorded.
_RECEIPT_LOOKBACK = 10


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def recorded_head_sha(raw_result: Any) -> str:
    """Return the exact commit a QA run says it verified."""
    payload = _json_object(raw_result)
    for key in ("verification_tree", "code_identity"):
        identity = payload.get(key)
        if isinstance(identity, dict) and identity.get("head_sha"):
            return str(identity["head_sha"]).strip()
        if isinstance(identity, dict) and identity.get("sha"):
            return str(identity["sha"]).strip()
    return ""


def _evidence_sha(conn: Any, item_id: int) -> str:
    from yoke_core.domain.dash_execution import (
        DASH_EVIDENCE_SECTION,
        read_json_section,
    )

    evidence = read_json_section(conn, item_id=item_id, section=DASH_EVIDENCE_SECTION)
    if not evidence:
        return ""
    return str(evidence.get("commit_sha") or "").strip()


def _receipt_shas(conn: Any, item_id: int) -> list[str]:
    """The landing and merge commits the newest merge receipt recorded."""
    from yoke_core.domain.standalone_item_merge_receipt import RECEIPT_EVENT_NAME

    if not _table_exists(conn, "events"):
        return []
    placeholder = _placeholder(conn)
    rows = conn.execute(
        "SELECT envelope FROM events "
        f"WHERE event_name = {placeholder} AND item_id = {placeholder} "
        f"ORDER BY id DESC LIMIT {_RECEIPT_LOOKBACK}",
        (RECEIPT_EVENT_NAME, str(int(item_id))),
    ).fetchall()
    landing = ""
    merged = ""
    for row in rows:
        context = _json_object(_row_value(row, "envelope", 0)).get("context")
        if not isinstance(context, dict):
            continue
        landing = landing or str(context.get("commit_sha") or "").strip()
        merged = merged or str(context.get("merge_sha") or "").strip()
    return [landing, merged]


def _newest_passing_ci_head(conn: Any, item_id: int) -> str:
    """The newest tree CI proved green for this item.

    Merge-gate CI evidence — the local engine's post-integration run and the
    merge queue's batch receipt alike — lands as a passing ``ci_run`` row, so
    the newest one names the integrated head the merge actually validated.
    """
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return ""
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT r.raw_result FROM qa_runs r "
        "JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id = {placeholder} AND r.performed_by = 'ci_run' "
        "AND r.verdict = 'pass' ORDER BY r.id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    return recorded_head_sha(_row_value(row, "raw_result", 0)) if row else ""


def _lane_sha(conn: Any, item_id: int) -> str:
    if not (
        _table_exists(conn, "item_worktrees")
        and _column_exists(conn, "item_worktrees", "commit_sha")
    ):
        return ""
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT commit_sha FROM item_worktrees "
        f"WHERE item_id = {placeholder} AND commit_sha IS NOT NULL "
        "ORDER BY CASE WHEN state = 'active' THEN 0 ELSE 1 END, id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    return str(_row_value(row, "commit_sha", 0) or "").strip() if row else ""


def accepted_merging_shas(conn: Any, item_id: int) -> tuple[str, ...]:
    """Every head a terminal blocking run may be recorded against."""
    candidates = [
        _evidence_sha(conn, item_id),
        *_receipt_shas(conn, item_id),
        _newest_passing_ci_head(conn, item_id),
        _lane_sha(conn, item_id),
    ]
    return tuple(dict.fromkeys(sha for sha in candidates if sha))


__all__ = ["accepted_merging_shas", "recorded_head_sha"]
