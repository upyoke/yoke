"""Operator recovery for an item whose merge timestamp was never recorded.

A terminal item is immutable. Once an item reaches a terminal workflow
stage its records are frozen, and no general write path reopens them --
the scalar-update surface requires a work claim, and a claim cannot be
acquired against a terminal item. That immutability is deliberate, so the
one provenance field a merge outside the merge boundary can leave unset --
``items.merged_at`` -- gets a single narrow human-only correction surface
instead of a general terminal write path.

Sibling of :mod:`yoke_core.domain.coordination_leases_operator`, sharing
its recovery properties: the surface refuses a hook context, demands a
non-empty operator reason, and emits its WARN event BEFORE the mutation
lands, so a telemetry outage cannot mask a successful operator action.

The guardrails are what keep this from becoming the general terminal write
path the contract excludes:

* the item must already be terminal -- a live item lands through the merge
  boundary, which stamps the timestamp itself;
* ``merged_at`` must be unset -- this fills a gap, it never rewrites
  recorded provenance;
* the timestamp must parse in the stored format and must not be in the
  future.

Rationale and the terminal-immutability contract: ``.yoke/docs/lifecycle.md``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from yoke_core.domain.project_identity import render_item_ref

MERGED_AT_CORRECTION_EVENT = "OperatorMergedAtCorrection"

# The stored shape every merged_at writer emits; a correction must match it
# so downstream readers cannot tell a corrected row from a stamped one.
MERGED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class MergedAtCorrectionError(RuntimeError):
    """A merge-timestamp correction was refused."""


class MergedAtCorrectionHookContextError(MergedAtCorrectionError):
    """The correction was attempted from a hook context."""


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _parse_merged_at(merged_at: str, *, now: Optional[datetime]) -> str:
    candidate = (merged_at or "").strip()
    if not candidate:
        raise MergedAtCorrectionError("merged_at must be a non-empty timestamp")
    try:
        parsed = datetime.strptime(candidate, MERGED_AT_FORMAT)
    except ValueError as exc:
        raise MergedAtCorrectionError(
            f"merged_at must match {MERGED_AT_FORMAT} "
            f"(for example 2026-08-02T14:30:00Z); got {candidate!r}"
        ) from exc
    parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if parsed > reference:
        raise MergedAtCorrectionError(
            f"merged_at {candidate} is in the future; a correction records "
            "when the branch actually landed"
        )
    return candidate


def _item_state(conn: Any, item_id: int) -> tuple[str, str]:
    placeholder = _placeholder(conn)
    row = conn.execute(
        f"SELECT status, merged_at FROM items WHERE id = {placeholder}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise MergedAtCorrectionError(f"item {item_id} does not exist")
    return (
        str(_row_value(row, "status", 0) or ""),
        str(_row_value(row, "merged_at", 1) or ""),
    )


def _require_terminal(conn: Any, item_id: int, status: str, item_ref: str) -> None:
    from yoke_core.domain.item_terminal_resources import terminal_stage_ids
    from yoke_core.domain.workflow_item_binding_validation import (
        load_item_workflow_runtime,
    )

    runtime = load_item_workflow_runtime(conn, int(item_id))
    if status not in terminal_stage_ids(runtime):
        raise MergedAtCorrectionError(
            f"{item_ref} is at {status!r}, not a terminal stage. A live item "
            "records its merge through the merge boundary "
            f"(`yoke merge item {item_ref}`), which stamps merged_at itself; "
            "this surface only repairs an item already frozen without it."
        )


def operator_correct_merged_at(
    conn: Any,
    item_id: int,
    merged_at: str,
    operator_reason: str,
    *,
    session_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Human-only repair of a terminal item's unset ``merged_at``.

    Refuses invocation from a hook context (``YOKE_HOOK_EVENT`` set), emits
    a WARN :data:`MERGED_AT_CORRECTION_EVENT` *before* the update lands
    (ledger-first), and then writes the timestamp.

    Returns a summary dict describing the corrected item; raises
    :class:`MergedAtCorrectionError` when any guardrail refuses.
    """
    hook_event = os.environ.get("YOKE_HOOK_EVENT")
    if hook_event:
        raise MergedAtCorrectionHookContextError(
            "Merge-timestamp correction cannot be invoked from a hook context "
            f"(YOKE_HOOK_EVENT={hook_event}). This command is human-only."
        )

    if not operator_reason or not operator_reason.strip():
        raise MergedAtCorrectionError("operator_reason must be a non-empty string")

    resolved_merged_at = _parse_merged_at(merged_at, now=now)
    status, existing = _item_state(conn, item_id)
    item_ref = render_item_ref(conn, int(item_id))

    if existing:
        raise MergedAtCorrectionError(
            f"{item_ref} already records merged_at={existing}. Recorded merge "
            "provenance is immutable; this surface only fills an unset value."
        )

    _require_terminal(conn, int(item_id), status, item_ref)

    context = {
        "item_id": int(item_id),
        "item_ref": item_ref,
        "status": status,
        "merged_at": resolved_merged_at,
        "operator_reason": operator_reason,
    }
    _emit_merged_at_correction(
        session_id=session_id or "",
        item_id=int(item_id),
        context=context,
    )

    placeholder = _placeholder(conn)
    conn.execute(
        f"UPDATE items SET merged_at = {placeholder} WHERE id = {placeholder}",
        (resolved_merged_at, int(item_id)),
    )
    conn.commit()

    return {
        "corrected": True,
        "item_id": int(item_id),
        "item_ref": item_ref,
        "status": status,
        "merged_at": resolved_merged_at,
        "operator_reason": operator_reason,
        "operator_session_id": session_id or "",
    }


def _emit_merged_at_correction(
    *,
    session_id: str,
    item_id: int,
    context: Dict[str, Any],
) -> None:
    """Fire the WARN correction event via the shared emitter."""
    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            MERGED_AT_CORRECTION_EVENT,
            event_kind="system",
            event_type="item_lifecycle",
            source_type="api",
            session_id=session_id,
            item_id=str(item_id),
            severity="WARN",
            outcome="completed",
            context=context,
        )
    except Exception:
        # Best-effort telemetry; the correction proceeds so recovery is not
        # wedged by a telemetry outage.
        pass


__all__ = [
    "MERGED_AT_CORRECTION_EVENT",
    "MERGED_AT_FORMAT",
    "MergedAtCorrectionError",
    "MergedAtCorrectionHookContextError",
    "operator_correct_merged_at",
]
