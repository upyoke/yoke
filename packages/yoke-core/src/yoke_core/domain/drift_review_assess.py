"""Drift-review classifier and orchestrator (sibling of ``drift_review``).

Houses the bounded, read-only classifier that maps a delivered delta to one
of four drift-review outcomes (``neither``, ``frontier_only``, ``sml_only``,
``both``) and the public ``assess_post_delivery_drift`` entry point that
ties together checkpoint -> delta -> trigger -> classify.

The trigger heuristic, checkpoint anchor, delta query, and the
``DriftReviewResult`` dataclass live in :mod:`yoke_core.domain.drift_review`;
this module imports them rather than reimplementing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain.drift_review import (
    DEFAULT_TRIGGER_THRESHOLD,
    DriftReviewResult,
    _get_checkpoint_start,
    _get_delivered_items,
    should_trigger_review,
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _classify_drift(
    conn: Any,
    project: str,
    delivered_items: List[Dict[str, Any]],
    checkpoint_start: Optional[str],
) -> DriftReviewResult:
    """Run the bounded read-only drift-review classifier.

    Examines the titles and priority of delivered items and recent
    frontier/SML state to produce a 4-way classification.

    Heuristic classification rules:
    - Items whose titles mention strategy, SML, mission, vision,
      landscape, master-plan, or strategize -> SML impact.
    - Items whose titles mention frontier, scheduler, priority, feed,
      dependency, ranking, or backlog -> frontier impact.
    - Both sets overlap -> ``both``.
    - Neither -> ``neither``.
    """
    sml_keywords = {
        "strategy", "sml", "mission", "vision", "landscape",
        "master-plan", "strategize", "strategic",
    }
    frontier_keywords = {
        "frontier", "scheduler", "priority", "feed", "dependency",
        "ranking", "backlog", "payoff", "rank", "wip",
    }

    has_sml_impact = False
    has_frontier_impact = False
    item_ids: List[str] = []
    latest_delivered = checkpoint_start or ""

    for item in delivered_items:
        item_id = f"YOK-{item['id']}"
        item_ids.append(item_id)
        title_lower = (item.get("title") or "").lower()
        delivered_at = item.get("delivered_at", "")
        if delivered_at and delivered_at > latest_delivered:
            latest_delivered = delivered_at

        for kw in sml_keywords:
            if kw in title_lower:
                has_sml_impact = True
                break
        for kw in frontier_keywords:
            if kw in title_lower:
                has_frontier_impact = True
                break

    # Determine classification
    if has_sml_impact and has_frontier_impact:
        classification = "both"
        summary = (
            f"{len(delivered_items)} delivered item(s) impact both SML "
            f"and frontier."
        )
    elif has_sml_impact:
        classification = "sml_only"
        summary = (
            f"{len(delivered_items)} delivered item(s) impact the SML."
        )
    elif has_frontier_impact:
        classification = "frontier_only"
        summary = (
            f"{len(delivered_items)} delivered item(s) impact the frontier."
        )
    else:
        classification = "neither"
        summary = (
            f"{len(delivered_items)} delivered item(s) have no detected "
            f"SML or frontier impact."
        )

    return DriftReviewResult(
        classification=classification,
        summary=summary,
        checkpoint_start=checkpoint_start or "",
        reviewed_through=latest_delivered,
        delivered_items=item_ids,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _normalize_project_scope(project_scope) -> List[str]:
    """Coerce legacy and current drift-review scope shapes to a list."""
    if isinstance(project_scope, str):
        return [project_scope]
    scope = list(project_scope) if project_scope else []
    return scope or ["yoke"]


def _combined_checkpoint_start(checkpoints: List[Optional[str]]) -> Optional[str]:
    """Return the earliest real checkpoint represented in a scoped review."""
    if any(checkpoint is None for checkpoint in checkpoints):
        return None
    concrete = [checkpoint for checkpoint in checkpoints if checkpoint]
    if not concrete:
        return None
    return min(concrete)


def assess_post_delivery_drift(
    conn: Any,
    project_scope,
    threshold: int = DEFAULT_TRIGGER_THRESHOLD,
) -> Optional[DriftReviewResult]:
    """Run the full drift-review pipeline: checkpoint -> delta -> trigger -> classify.

    ``project_scope`` accepts either a list of project ids (current contract)
    or a single project id string (legacy). For a list, the delivered delta is
    collected from every scoped project while preserving each project's own
    checkpoint anchor.

    Returns ``None`` if the trigger does not fire (no review needed).
    Returns a ``DriftReviewResult`` if the trigger fires and classification
    succeeds.
    Raises ``RuntimeError`` if the trigger fires but classification fails
    (the caller must escalate).
    """
    scope = _normalize_project_scope(project_scope)
    checkpoints: List[Optional[str]] = []
    delivered: List[Dict[str, Any]] = []
    for project in scope:
        checkpoint = _get_checkpoint_start(conn, project)
        checkpoints.append(checkpoint)
        delivered.extend(_get_delivered_items(conn, project, checkpoint))

    if not should_trigger_review(delivered, threshold=threshold):
        return None

    try:
        result = _classify_drift(
            conn,
            ",".join(scope),
            delivered,
            _combined_checkpoint_start(checkpoints),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Drift review triggered but classification failed for "
            f"project scope {scope}: {exc}"
        ) from exc

    return result
