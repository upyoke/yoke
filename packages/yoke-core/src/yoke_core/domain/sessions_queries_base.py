"""Session ID normalization and offer-compatibility filtering."""

from __future__ import annotations

from yoke_contracts.timestamps import iso8601_now
from typing import Any, Dict, Optional

from . import db_backend
from .sessions_analytics import _NEXT_STEP_TO_PATH
from .workflow_runtime import WorkflowRuntime, load_item_workflow_runtime


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_claim_item_id(item_id: Any) -> str:
    """Normalize an item id decoded from ``work_claims.scope``."""
    text = str(item_id)
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def normalize_session_item_id(item_id: Any) -> str:
    """Normalize typed session item-id columns for comparisons."""
    text = str(item_id)
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def display_claim_item_id(
    item_id: Optional[str],
    conn: Any = None,
) -> Optional[str]:
    """Render a claim's item id for display.

    The ``item_id`` key in ``work_claims.scope`` stores the internal bare
    ``items.id``. The ref
    an operator should see is project-scoped
    (``{projects.public_item_prefix}-{items.project_sequence}``), which can
    diverge from the internal id. When ``conn`` is supplied, resolve the true
    public ref via ``render_item_ref`` (which itself falls back to a
    prefix+id string when the item row is missing). Without a connection —
    routing callers that resolve work back by internal id — return the bare
    internal-id string; a prefixed form here would leak a wrong public ref
    for items whose sequence diverges from the internal id.
    """
    if item_id is None:
        return None
    normalized = normalize_claim_item_id(str(item_id))
    if normalized.isdigit():
        if conn is not None:
            from .project_identity import render_item_ref

            return render_item_ref(conn, int(normalized))
        return normalized
    return str(item_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return iso8601_now()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row)


def _required_path_for_step(step: Any) -> Optional[str]:
    """Return the canonical downstream path name for a scheduled step."""
    next_step = getattr(step, "next_step", None)
    if next_step is None:
        return None
    if hasattr(next_step, "value"):
        next_step = next_step.value
    return _NEXT_STEP_TO_PATH.get(str(next_step))


# ---------------------------------------------------------------------------
# Routing / compatibility
# ---------------------------------------------------------------------------


def derive_required_path(
    workflow: WorkflowRuntime,
    status: str,
) -> Optional[str]:
    """Derive the canonical downstream path for claimed work.

    Uses the scheduler's definition-selected routing truth.

    Returns the canonical path name (e.g., ``implement``, ``polish``,
    ``usher``) or ``None`` if the mapping cannot be resolved.
    """
    from .frontier_classify import classify_next_action
    from .scheduler import _compute_next_step

    adapter = classify_next_action(workflow, status)
    result = _compute_next_step(
        adapter,
        probe_path_claim_activation=(workflow.requires_item_path_claim_probe(status)),
    )
    ns = result.next_step
    if hasattr(ns, "value"):
        ns = ns.value
    return _NEXT_STEP_TO_PATH.get(str(ns))


def resolve_claimed_work_context(
    conn: Any,
    claim: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve current routing metadata for a raw claim row."""
    from .work_claim_targets import from_row as target_from_row

    target = target_from_row(claim)
    item_id = target.item_id
    epic_id = target.epic_id
    task_num = target.task_num
    workflow: Optional[WorkflowRuntime] = None
    status: Optional[str] = claim.get("status")
    required_path: Optional[str] = claim.get("required_path")

    lookup_id: Optional[int] = None
    if item_id:
        try:
            lookup_id = int(item_id)
        except (TypeError, ValueError):
            lookup_id = None
    elif epic_id is not None:
        lookup_id = int(epic_id)

    if lookup_id is not None:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}",
            (lookup_id,),
        ).fetchone()
        if row is not None:
            status = row["status"] or status
            workflow = load_item_workflow_runtime(conn, lookup_id)

    # Active epic-task claims always resume through conduct.
    if epic_id is not None and task_num is not None and not item_id:
        required_path = required_path or "conduct"
    elif required_path is None and workflow is not None and status:
        required_path = derive_required_path(workflow, status)

    return {
        "workflow_id": workflow.workflow_id if workflow else None,
        "workflow_version_id": workflow.workflow_version_id if workflow else None,
        "workflow_version": workflow.version if workflow else None,
        "status": status,
        "required_path": required_path,
    }
