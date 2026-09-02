"""Shared QA lifecycle event helpers.

Leaf module owned by the QA domain. Provides the event-emission surface
used by ``qa_requirements``, ``qa_execution``, and their focused sibling
modules.

The ``emit_qa_requirement_event`` helper accepts the union of features from
the duplicates: it supports an ``extra_detail`` mapping that callers can use
to merge additional fields into the event detail after the conditional
``rationale`` and ``source`` keys.

Post-state-commit callers emit best-effort: if the ``events.emit_event``
import or call raises for any reason, the helper returns silently. The
gateway commits a successful caller-connection write, so those callers need
no local commit discipline.

A caller that writes its row inside a transaction it has not yet committed
passes ``transactional=True`` instead. The event then rides that same
transaction, so a requirement row and its creation event become durable
together or not at all — the guarantee the plan-case materialization, the
merge-gate CI requirement, and the no-tests review floor rely on, since each
writes rows a later caller commits. Transactional emission is not
best-effort: a write the gateway could not record raises
:class:`QaRequirementEventNotRecorded` rather than leaving the row silently
dark, because on Postgres the failed write has already aborted the caller's
transaction and continuing would report a success the database never kept.

This module imports only ``typing``, ``yoke_core.domain.db_helpers``, and
lazily imports ``emit_event`` from ``.events`` inside a try/except. It does
NOT import any ``yoke_core.domain.qa*`` sibling.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_core.domain.db_helpers import query_one


class QaRequirementEventNotRecorded(RuntimeError):
    """A transactional requirement write demanded an event that never landed."""


#: Emission outcomes that mean the gateway deliberately declined to write a
#: row: a capture or isolation test mode, an operator severity floor above
#: the event, or a schema with no ``events`` table. None of them leaves the
#: caller's transaction aborted, so a transactional caller continues.
DELIBERATE_NON_WRITE_REASONS = frozenset(
    {
        "capture_only",
        "isolation_gate_refused",
        "severity_filtered",
        "events_table_missing",
    }
)


def _not_recorded(event_name: str, requirement_id: int, reason: str) -> str:
    """Name the failed emission and the step that recovers it."""
    return (
        f"QA requirement {requirement_id} was written but its {event_name} "
        f"event did not land (reason: {reason}); the requirement write is "
        "abandoned rather than left silently dark. Recovery: inspect the "
        "events gateway for that reason, confirm the ledger is writable with "
        f"`yoke events query --event-name {event_name}`, then re-run the "
        "operation that created the requirement."
    )


# ---------------------------------------------------------------------------
# Failure recovery shared by both emission helpers
# ---------------------------------------------------------------------------

def _safe_rollback(conn) -> None:
    """Clear an aborted transaction on the shared connection.

    Postgres aborts the whole transaction when any statement fails; a
    best-effort emission that swallows its own error must roll back so the
    caller's post-commit work is not blocked by ``InFailedSqlTransaction``.
    Every caller commits its own work before emitting, so nothing committed is
    lost. No-op-safe on SQLite.
    """
    try:
        conn.rollback()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_requirement_event_target(row: Any) -> Tuple[Optional[str], Optional[int]]:
    """Map a qa_requirements row to canonical event item/task fields.

    ``row`` may be a ``sqlite3.Row`` or a dict with the same column-name
    indexing semantics. Returns ``(public_ref, task_num_ref)`` where:

    - ``public_ref`` is the stringified ``item_id`` for item-target rows,
      the stringified ``epic_id`` for epic-task-target rows, or the raw
      ``deployment_run_id`` string for deployment-target rows.
    - ``task_num_ref`` is an int only for epic-task-target rows.

    Returns ``(None, None)`` when ``row`` is None or has no resolvable
    target columns.
    """
    public_ref: Optional[str] = None
    task_num_ref: Optional[int] = None
    if row is not None:
        if row["item_id"] is not None:
            public_ref = str(int(row["item_id"]))
        elif row["epic_id"] is not None:
            public_ref = str(int(row["epic_id"]))
            task_num_ref = int(row["task_num"]) if row["task_num"] is not None else None
        elif row["deployment_run_id"] is not None:
            public_ref = str(row["deployment_run_id"])
    return public_ref, task_num_ref


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
    transactional: bool = False,
) -> None:
    """Lifecycle emission for QA requirements.

    Resolves the event target from ``target_row`` when provided; otherwise
    queries ``qa_requirements`` by ``requirement_id`` to recover the
    item/epic/deployment target. Builds the standard QA lifecycle envelope
    (event_kind=``lifecycle``, event_type=``qa_lifecycle``,
    source_type=``system``, severity=``INFO``) and merges ``extra_detail``
    into the context detail last so callers can override or extend the
    base keys.

    Emission is best-effort by default, for callers that already committed
    their row. Pass ``transactional=True`` to leave the event on the
    caller's open transaction so the row and its event commit together; that
    mode raises :class:`QaRequirementEventNotRecorded` instead of returning
    when the event could not be recorded.
    """
    try:
        from .events import emit_event
    except Exception as exc:
        if transactional:
            raise QaRequirementEventNotRecorded(
                _not_recorded(event_name, requirement_id, "events_gateway_unavailable")
            ) from exc
        return

    req_row = target_row
    if req_row is None:
        try:
            req_row = query_one(
                conn,
                "SELECT item_id, epic_id, task_num, deployment_run_id FROM qa_requirements WHERE id = %s",
                (requirement_id,),
            )
        except Exception as exc:
            if transactional:
                raise QaRequirementEventNotRecorded(
                    _not_recorded(
                        event_name, requirement_id, "requirement_target_unreadable"
                    )
                ) from exc
            return

    public_ref, task_num_ref = resolve_requirement_event_target(req_row)

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
        result = emit_event(
            event_name,
            event_kind="lifecycle",
            event_type="qa_lifecycle",
            source_type="system",
            severity="INFO",
            item_id=public_ref,
            task_num=task_num_ref,
            context={"detail": detail},
            db_path=db_path,
            conn=conn,
            transactional=transactional,
        )
    except Exception as exc:
        if transactional:
            raise QaRequirementEventNotRecorded(
                _not_recorded(event_name, requirement_id, "emit_event_raised")
            ) from exc
        _safe_rollback(conn)
        return
    if getattr(result, "ok", False):
        return
    if transactional:
        reason = str(getattr(result, "reason", "") or "unknown")
        if reason in DELIBERATE_NON_WRITE_REASONS:
            return
        raise QaRequirementEventNotRecorded(
            _not_recorded(event_name, requirement_id, reason)
        )
    _safe_rollback(conn)


# ---------------------------------------------------------------------------
# QA run lifecycle events
# ---------------------------------------------------------------------------

def emit_qa_run_event(
    conn,
    *,
    db_path: Optional[str],
    event_name: str,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    verdict: Optional[str] = None,
    verdict_reason: Optional[str] = None,
) -> None:
    """Best-effort lifecycle emission for QA runs.

    Looks up the parent ``qa_requirements`` row by ``requirement_id`` to
    resolve the event target, then emits a lifecycle envelope with
    event_type=``qa_execution``. ``verdict`` is included in the context
    detail only when not None, together with its reason when supplied.
    """
    from yoke_core.domain.qa_review_requests import (
        maybe_ensure_qa_review_request,
    )
    try:
        maybe_ensure_qa_review_request(
            conn, verdict=verdict, requirement_id=requirement_id, run_id=run_id,
        )
    except Exception:
        _safe_rollback(conn)
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

    public_ref, task_num_ref = resolve_requirement_event_target(req_row)

    detail: dict = {
        "run_id": run_id,
        "requirement_id": requirement_id,
        "qa_kind": qa_kind,
    }
    if verdict is not None:
        detail["verdict"] = verdict
    if verdict_reason is not None:
        detail["verdict_reason"] = verdict_reason

    try:
        result = emit_event(
            event_name,
            event_kind="lifecycle",
            event_type="qa_execution",
            source_type="system",
            severity="INFO",
            item_id=public_ref,
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
    if not getattr(result, "ok", False):
        _safe_rollback(conn)
        return
