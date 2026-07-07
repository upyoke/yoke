"""Project-scoped post-delivery drift review.

Replaces the ambient stale-bit decisioning model (``sml_stale``,
``sml_basis``, ``graph_stale``) with a bounded review that classifies
delivered work into one of four outcomes:

    ``neither`` -- delivered work impacts neither SML nor frontier
    ``frontier_only`` -- only frontier ordering/materialization affected
    ``sml_only`` -- only the Strategic Markdown Layer affected
    ``both`` -- both SML and frontier affected

The review is **read-only** and never mutates SML or frontier state.

Key concepts:

- **Checkpoint anchor**: the latest project-scoped row in
  ``strategy_checkpoints`` (written by strategize finalize and
  drift-review completion — ``yoke_core.domain.strategy_checkpoints``).
- **Delivered delta**: items in the project whose ``merged_at`` is newer
  than the checkpoint, falling back to ``item_status_transitions`` rows
  into ``release`` / ``done`` for legacy rows where ``merged_at`` is null.
- **Trigger heuristic (v0)**: priority-tier weighting (``high=3``,
  ``medium=2``, ``low=1``).  Fires when cumulative weight crosses the
  configured threshold (default 5) or any ``high``-priority item is
  delivered.

This module owns the trigger heuristic, the checkpoint anchor, the
delivered-delta query, and the ``DriftReviewResult`` dataclass.  The
classifier and full ``assess_post_delivery_drift`` entry point live in
:mod:`yoke_core.domain.drift_review_assess`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Priority-tier weights for the v0 trigger heuristic.
_PRIORITY_WEIGHT: Dict[str, int] = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

#: Default cumulative-weight threshold for the trigger heuristic.
DEFAULT_TRIGGER_THRESHOLD = 5


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_if_postgres(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        try:
            conn.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftReviewResult:
    """Outcome of a bounded post-delivery drift review.

    Attributes:
        classification: One of ``neither``, ``frontier_only``,
            ``sml_only``, ``both``.
        summary: Short human-readable explanation of the classification.
        checkpoint_start: ISO 8601 timestamp of the checkpoint anchor.
        reviewed_through: ISO 8601 timestamp of the latest delivered
            work included in the review.
        delivered_items: ``YOK-N`` IDs reviewed.
    """

    classification: str
    summary: str
    checkpoint_start: str
    reviewed_through: str
    delivered_items: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for embedding in FrontierState."""
        return {
            "classification": self.classification,
            "summary": self.summary,
            "checkpoint_start": self.checkpoint_start,
            "reviewed_through": self.reviewed_through,
            "delivered_items": list(self.delivered_items),
        }


# ---------------------------------------------------------------------------
# Checkpoint anchor
# ---------------------------------------------------------------------------


def _get_checkpoint_start(
    conn: Any,
    project: Any,
) -> Optional[str]:
    """Return the ISO 8601 timestamp of the latest project checkpoint.

    Checkpoints are ``strategy_checkpoints`` rows written by strategize
    finalize and drift-review completion. ``project`` accepts a slug or
    a numeric project id (the offer dispatch passes ids). Returns
    ``None`` when no checkpoint exists (i.e. the system has never run
    strategize or drift review for this project).
    """
    from yoke_core.domain.strategy_checkpoints import latest_checkpoint_at

    return latest_checkpoint_at(conn, project)


# ---------------------------------------------------------------------------
# Delivered delta
# ---------------------------------------------------------------------------


def _get_delivered_items(
    conn: Any,
    project: str,
    checkpoint_start: Optional[str],
) -> List[Dict[str, Any]]:
    """Query items delivered since the checkpoint.

    Primary signal: ``items.merged_at`` newer than *checkpoint_start*.
    Fallback (legacy rows with null ``merged_at``): project-scoped
    ``item_status_transitions`` row into ``release`` or ``done`` after
    the checkpoint.
    """
    if checkpoint_start is None:
        # No checkpoint -- treat all merged items as the delta.
        # Use a generous floor so the first review is bounded.
        checkpoint_start = "1970-01-01T00:00:00Z"

    items: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    project_id = resolve_project_id(conn, project)

    # Primary: merged_at
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id, title, priority, merged_at FROM items"
            f" WHERE project_id = {p} AND merged_at IS NOT NULL AND merged_at > {p}",
            (project_id, checkpoint_start),
        ).fetchall()
        for r in rows:
            seen_ids.add(r[0])
            items.append({
                "id": r[0],
                "title": r[1],
                "priority": r[2] or "low",
                "delivered_at": r[3],
            })
    except db_backend.operational_error_types(conn):
        _rollback_if_postgres(conn)
        pass

    # Fallback: transition rows into release/done for items without merged_at
    try:
        p = _p(conn)
        rows = conn.execute(
            f"SELECT DISTINCT t.item_id, t.to_status, t.created_at"
            f" FROM item_status_transitions t"
            f" WHERE t.task_num IS NULL"
            f"   AND t.to_status IN ('release', 'done')"
            f"   AND t.project_id = {p}"
            f"   AND t.created_at > {p}",
            (project_id, checkpoint_start),
        ).fetchall()
        for r in rows:
            item_id = r[0]
            if item_id and item_id not in seen_ids:
                # Look up item metadata
                try:
                    p = _p(conn)
                    meta = conn.execute(
                        f"SELECT title, priority FROM items WHERE id = {p}",
                        (item_id,),
                    ).fetchone()
                    items.append({
                        "id": item_id,
                        "title": meta[0] if meta else "",
                        "priority": (meta[1] if meta else "low") or "low",
                        "delivered_at": r[2],
                    })
                    seen_ids.add(item_id)
                except db_backend.operational_error_types(conn):
                    _rollback_if_postgres(conn)
                    pass
    except db_backend.operational_error_types(conn):
        _rollback_if_postgres(conn)
        pass

    return items


# ---------------------------------------------------------------------------
# Trigger heuristic
# ---------------------------------------------------------------------------


def should_trigger_review(
    delivered_items: List[Dict[str, Any]],
    threshold: int = DEFAULT_TRIGGER_THRESHOLD,
) -> bool:
    """Decide whether the delivered delta warrants a drift review.

    v0 heuristic: priority-tier weighting.
    - high=3, medium=2, low=1
    - Fires when cumulative weight >= threshold or any high-priority
      item is in the delta.
    """
    if not delivered_items:
        return False

    weight = 0
    for item in delivered_items:
        pri = item.get("priority", "low")
        w = _PRIORITY_WEIGHT.get(pri, 1)
        weight += w
        if pri == "high":
            return True  # Immediate trigger

    return weight >= threshold


__all__ = [
    "DEFAULT_TRIGGER_THRESHOLD",
    "DriftReviewResult",
    "_get_checkpoint_start",
    "_get_delivered_items",
    "should_trigger_review",
]
