"""Which trees a merge proved, for the item that merge landed.

The terminal QA gate refuses an item whose blocking proof does not cover the
tree that landed. That comparison needs the landed tree's identity, and one
merge legitimately produces more than one: the lane head that entered the
merge, the integrated head the merge gate validated, and — under a merge
queue — the PR-entry head GitHub verified after rebasing the lane. The
train's combined head is a commit no single member ever ran against, so
demanding one SHA satisfy every requirement strands every queue-landed item.

The accepted set is what the merge boundary recorded: the receipt's landing
and merge commits, every distinct passing ``ci_run`` identity (the newest
PR-entry head and the newest train receipt), execution evidence, and the
lane column. Recording the train receipt last must not displace the
PR-entry SHA the item's own case verified.

When that train receipt names this item's merge identity, the queue run is
the covering verdict for the merged tree. Passing blocking runs then join
the set rather than demanding a per-item re-verdict at the integrated head.
A run recorded at none of those predates the merge and is still refused.

Rationale and rejected alternatives: ``docs/archive/decisions/
merge-close-out-completion.md``.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists

# How far back to read this item's merge receipts. One merge writes a
# pre-merge row and a completion row; the window covers repeated retries
# while still folding newest-first, so a superseded attempt never outranks
# the identity the latest attempt recorded.
_RECEIPT_LOOKBACK = 10
_CI_RUN_LOOKBACK = 20


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


def _batch_block(raw_result: Any) -> dict[str, Any]:
    block = _json_object(raw_result).get("merge_queue_batch")
    return block if isinstance(block, dict) else {}


def ci_run_identity_shas(raw_results: Sequence[Any]) -> tuple[str, ...]:
    """PR-entry head plus train head and merge, from newest-first ``ci_run`` rows.

    A later batch receipt is a different tree than the member's command-ci
    entry run. Keeping only the newest SHA drops the entry head the blocking
    requirement still names, so both identities stay in the set.
    """
    entry_head = ""
    batch_head = ""
    batch_merge = ""
    for raw in raw_results:
        block = _batch_block(raw)
        head = recorded_head_sha(raw)
        if block:
            if not batch_head:
                batch_head = head or str(block.get("combined_head_sha") or "").strip()
            if not batch_merge:
                batch_merge = str(block.get("merge_sha") or "").strip()
        elif not entry_head:
            entry_head = head
        if entry_head and batch_head and batch_merge:
            break
    return tuple(
        dict.fromkeys(sha for sha in (entry_head, batch_head, batch_merge) if sha)
    )


def queue_batch_covers_receipt(
    raw_results: Sequence[Any],
    receipt_shas: Sequence[str],
) -> bool:
    """Whether the newest train receipt names this item's merge identity."""
    identity = {sha for sha in receipt_shas if sha}
    if not identity:
        return False
    for raw in raw_results:
        block = _batch_block(raw)
        if not block:
            continue
        head = (
            recorded_head_sha(raw) or str(block.get("combined_head_sha") or "").strip()
        )
        merge_sha = str(block.get("merge_sha") or "").strip()
        return bool(
            (merge_sha and merge_sha in identity) or (head and head in identity)
        )
    return False


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


def _passing_ci_raw_results(conn: Any, item_id: int) -> list[Any]:
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    placeholder = _placeholder(conn)
    rows = conn.execute(
        "SELECT r.raw_result FROM qa_runs r "
        "JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id = {placeholder} AND r.performed_by = 'ci_run' "
        "AND r.verdict = 'pass' ORDER BY r.id DESC "
        f"LIMIT {_CI_RUN_LOOKBACK}",
        (int(item_id),),
    ).fetchall()
    return [_row_value(row, "raw_result", 0) for row in rows]


def _passing_blocking_heads(conn: Any, item_id: int) -> list[str]:
    """Latest passing SHA on each blocking requirement, any performer."""
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    placeholder = _placeholder(conn)
    rows = conn.execute(
        "SELECT r.raw_result FROM qa_requirements q LEFT JOIN qa_runs r ON r.id = ("
        "SELECT latest.id FROM qa_runs latest "
        "WHERE latest.qa_requirement_id = q.id "
        "ORDER BY latest.id DESC LIMIT 1) "
        f"WHERE q.item_id = {placeholder} AND q.blocking_mode = 'blocking' "
        "AND q.waived_at IS NULL AND r.verdict = 'pass'",
        (int(item_id),),
    ).fetchall()
    return [
        sha
        for sha in (recorded_head_sha(_row_value(row, "raw_result", 0)) for row in rows)
        if sha
    ]


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
    receipts = _receipt_shas(conn, item_id)
    ci_runs = _passing_ci_raw_results(conn, item_id)
    candidates = [
        _evidence_sha(conn, item_id),
        *receipts,
        *ci_run_identity_shas(ci_runs),
        _lane_sha(conn, item_id),
    ]
    if queue_batch_covers_receipt(ci_runs, receipts):
        candidates.extend(_passing_blocking_heads(conn, item_id))
    return tuple(dict.fromkeys(sha for sha in candidates if sha))


__all__ = [
    "accepted_merging_shas",
    "ci_run_identity_shas",
    "queue_batch_covers_receipt",
    "recorded_head_sha",
]
