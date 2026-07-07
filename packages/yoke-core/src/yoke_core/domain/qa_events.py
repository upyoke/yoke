"""Shared QA lifecycle event helpers.

Leaf module owned by the QA domain. Provides the event-emission surface
used by ``qa_requirements``, ``qa_execution``, and their focused sibling
modules.

The ``emit_qa_requirement_event`` helper accepts the union of features from
the duplicates: it supports an ``extra_detail`` mapping that callers can use
to merge additional fields into the event detail after the conditional
``rationale`` and ``source`` keys.

All helpers are best-effort: if the ``events.emit_event`` import or call
raises for any reason, the helper returns silently. This mirrors the
existing try/except discipline that all duplicated copies use today.

This module imports only ``typing``, ``yoke_core.domain.db_helpers``, and
lazily imports ``emit_event`` from ``.events`` inside a try/except. It does
NOT import any ``yoke_core.domain.qa*`` sibling.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_core.domain.db_helpers import query_one


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_requirement_event_target(row: Any) -> Tuple[Optional[str], Optional[int]]:
    """Map a qa_requirements row to canonical event item/task fields.

    ``row`` may be a ``sqlite3.Row`` or a dict with the same column-name
    indexing semantics. Returns ``(item_ref, task_num_ref)`` where:

    - ``item_ref`` is the stringified ``item_id`` for item-target rows,
      the stringified ``epic_id`` for epic-task-target rows, or the raw
      ``deployment_run_id`` string for deployment-target rows.
    - ``task_num_ref`` is an int only for epic-task-target rows.

    Returns ``(None, None)`` when ``row`` is None or has no resolvable
    target columns.
    """
    item_ref: Optional[str] = None
    task_num_ref: Optional[int] = None
    if row is not None:
        if row["item_id"] is not None:
            item_ref = str(int(row["item_id"]))
        elif row["epic_id"] is not None:
            item_ref = str(int(row["epic_id"]))
            task_num_ref = int(row["task_num"]) if row["task_num"] is not None else None
        elif row["deployment_run_id"] is not None:
            item_ref = str(row["deployment_run_id"])
    return item_ref, task_num_ref


# ---------------------------------------------------------------------------
# QA requirement lifecycle events
# ---------------------------------------------------------------------------

def emit_qa_requirement_event(
    conn,
    *,
    db_path: Optional[str],
    event_name: str,
    requirement_id: int,
    qa_kind: str,
    qa_phase: str,
    rationale: Optional[str] = None,
    source: Optional[str] = None,
    target_row: Any = None,
    extra_detail: Optional[dict] = None,
) -> None:
    """Best-effort lifecycle emission for QA requirements.

    Resolves the event target from ``target_row`` when provided; otherwise
    queries ``qa_requirements`` by ``requirement_id`` to recover the
    item/epic/deployment target. Builds the standard QA lifecycle envelope
    (event_kind=``lifecycle``, event_type=``qa_lifecycle``,
    source_type=``system``, severity=``INFO``) and merges ``extra_detail``
    into the context detail last so callers can override or extend the
    base keys.
    """
    try:
        from .events import emit_event
    except Exception:
        return

    req_row = target_row
    if req_row is None:
        try:
            req_row = query_one(
                conn,
                "SELECT item_id, epic_id, task_num, deployment_run_id FROM qa_requirements WHERE id = %s",
                (requirement_id,),
            )
        except Exception:
            return

    item_ref, task_num_ref = resolve_requirement_event_target(req_row)

    detail: dict = {
        "requirement_id": requirement_id,
        "qa_kind": qa_kind,
        "qa_phase": qa_phase,
    }
    if rationale is not None:
        detail["rationale"] = rationale
    if source is not None:
        detail["source"] = source
    if extra_detail:
        detail.update(extra_detail)

    try:
        emit_event(
            event_name,
            event_kind="lifecycle",
            event_type="qa_lifecycle",
            source_type="system",
            severity="INFO",
            item_id=item_ref,
            task_num=task_num_ref,
            context={"detail": detail},
            db_path=db_path,
            conn=conn,
        )
    except Exception:
        return


# ---------------------------------------------------------------------------
# QA run lifecycle events
# ---------------------------------------------------------------------------

def _safe_rollback(conn) -> None:
    """Clear an aborted transaction on the shared connection.

    Postgres aborts the whole transaction when any statement fails; a
    best-effort emission that swallows its own error must roll back so the
    caller's post-commit work is not blocked by ``InFailedSqlTransaction``.
    Every caller of :func:`emit_qa_run_event` commits its own work before
    emitting, so nothing committed is lost. No-op-safe on SQLite.
    """
    try:
        conn.rollback()
    except Exception:
        pass


def emit_qa_run_event(
    conn,
    *,
    db_path: Optional[str],
    event_name: str,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    verdict: Optional[str] = None,
) -> None:
    """Best-effort lifecycle emission for QA runs.

    Looks up the parent ``qa_requirements`` row by ``requirement_id`` to
    resolve the event target, then emits a lifecycle envelope with
    event_type=``qa_execution``. ``verdict`` is included in the context
    detail only when not None.
    """
    try:
        from .events import emit_event
    except Exception:
        return

    try:
        req_row = query_one(
            conn,
            "SELECT item_id, epic_id, task_num, deployment_run_id FROM qa_requirements WHERE id = %s",
            (requirement_id,),
        )
    except Exception:
        _safe_rollback(conn)
        return

    item_ref, task_num_ref = resolve_requirement_event_target(req_row)

    detail: dict = {
        "run_id": run_id,
        "requirement_id": requirement_id,
        "qa_kind": qa_kind,
    }
    if verdict is not None:
        detail["verdict"] = verdict

    try:
        result = emit_event(
            event_name,
            event_kind="lifecycle",
            event_type="qa_execution",
            source_type="system",
            severity="INFO",
            item_id=item_ref,
            task_num=task_num_ref,
            context={"detail": detail},
            db_path=db_path,
            conn=conn,
        )
    except Exception:
        _safe_rollback(conn)
        return
    # A best-effort emission that did not write (e.g. the events table is
    # absent in a minimal test DB) leaves the shared transaction aborted on
    # Postgres; roll it back so the caller's post-commit work is not blocked.
    # A successful write stays pending for the caller's own commit.
    if not getattr(result, "ok", False):
        _safe_rollback(conn)
