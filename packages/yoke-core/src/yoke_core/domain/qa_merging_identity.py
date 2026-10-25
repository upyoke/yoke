"""Durable landing and lane identities for QA ancestry checks.

Start commits are observations. They never add themselves to the candidate
set: the lane, merge receipt and recorded close-out evidence own that set.
Queue receipts remain available independently for delivery diagnostics.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from yoke_core.domain.qa_latest_execution import latest_execution_id_sql

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists

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


def recorded_batch_blocks(conn: Any, item_id: int) -> tuple[dict[str, Any], ...]:
    """Every ``merge_queue_batch`` block this item recorded, newest first.

    The block a landing wrote is the durable answer to what validated the
    train, and it outlives the Actions window the landing read it from. A
    close-out that reaches it stops asking GitHub a question it already has
    the answer to.
    """
    return tuple(
        block
        for block in (
            _batch_block(raw) for raw in _passing_ci_raw_results(conn, item_id)
        )
        if block
    )


def recorded_batch_blocks_for_items(
    conn: Any,
    item_ids: Sequence[int],
) -> dict[int, tuple[dict[str, Any], ...]]:
    """:func:`recorded_batch_blocks` for many items, in one read.

    A roster asks this of every card it draws. The per-item read spent a
    round trip and two schema probes each to assemble rows that all live in
    the same two tables, so the same newest-first lookback is taken per item
    inside one statement instead. Items with no passing ``ci_run`` row are
    absent, which reads as no recorded block exactly as the empty tuple did.
    """
    if not item_ids or not (
        _table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")
    ):
        return {}
    ids = sorted({int(item_id) for item_id in item_ids})
    placeholder = _placeholder(conn)
    id_marks = ", ".join(placeholder for _ in ids)
    rows = conn.execute(
        "SELECT item_id, raw_result FROM ("
        "SELECT q.item_id AS item_id, r.raw_result AS raw_result, "
        "ROW_NUMBER() OVER (PARTITION BY q.item_id ORDER BY r.id DESC) "
        "AS run_rank "
        "FROM qa_runs r JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id IN ({id_marks}) AND r.performed_by = 'ci_run' "
        f"AND r.id=({latest_execution_id_sql('q.id')}) AND r.verdict='pass' AND r.completed_at IS NOT NULL"
        f") ranked WHERE run_rank <= {_CI_RUN_LOOKBACK} "
        "ORDER BY item_id, run_rank",
        tuple(ids),
    ).fetchall()
    by_item: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        block = _batch_block(_row_value(row, "raw_result", 1))
        if block:
            by_item.setdefault(int(_row_value(row, "item_id", 0)), []).append(block)
    return {item_id: tuple(blocks) for item_id, blocks in by_item.items()}


def _evidence_sha(conn: Any, item_id: int) -> str:
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_section

    evidence = read_json_section(conn, item_id=item_id, section=DASH_EVIDENCE_SECTION)
    if not evidence:
        return ""
    return str(evidence.get("commit_sha") or "").strip()


def _receipt_shas(conn: Any, item_id: int) -> list[str]:
    """The landing and merge commits the newest merge receipt recorded."""
    from yoke_core.domain.item_merge_receipt_document import landing_shas

    return landing_shas(conn, item_id)


def _passing_ci_raw_results(conn: Any, item_id: int) -> list[Any]:
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    placeholder = _placeholder(conn)
    rows = conn.execute(
        "SELECT r.raw_result FROM qa_runs r "
        "JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id = {placeholder} AND r.performed_by = 'ci_run' "
        f"AND r.id=({latest_execution_id_sql('q.id')}) AND r.verdict='pass' AND r.completed_at IS NOT NULL ORDER BY r.id DESC "
        f"LIMIT {_CI_RUN_LOOKBACK}",
        (int(item_id),),
    ).fetchall()
    return [_row_value(row, "raw_result", 0) for row in rows]


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
    """Candidate heads owned by this lane's landing and close-out records."""
    return tuple(
        dict.fromkeys(
            sha
            for sha in (
                _evidence_sha(conn, item_id),
                *_receipt_shas(conn, item_id),
                _lane_sha(conn, item_id),
            )
            if sha
        )
    )


__all__ = [
    "accepted_merging_shas",
    "recorded_batch_blocks",
    "recorded_batch_blocks_for_items",
    "queue_batch_covers_receipt",
    "recorded_head_sha",
]
