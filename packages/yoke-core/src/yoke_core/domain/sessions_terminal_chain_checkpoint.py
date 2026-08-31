"""Consume the chain checkpoint whose item just became terminal.

Terminal item cleanup releases work claims in item-lock order, then closes
the affected sessions under session locks after that transaction commits.
This module owns the matching checkpoint update.  The consumed outcome keeps
``chainable=True`` so a live ``/yoke do`` process may still take its next
offer, while the idle-session guard can distinguish finished work from budget
that is still waiting for a process to continue it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from .claim_chain_state import stamp_chain_checkpoint
from .project_identity import resolve_item_id
from .sessions_queries_base import _now_iso


OUTCOME_TERMINAL_ITEM_CLOSED = "terminal_item_closed"
TERMINAL_ITEM_CLOSED_LABEL = "terminal item closed; checkpoint consumed"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class TerminalItemSessionCloseout:
    """Session state changed after one item reached a terminal stage."""

    focus_released: tuple[str, ...] = ()
    checkpoint_consumed: tuple[str, ...] = ()


def _resolved_item_id(conn: Any, raw_item_id: Any) -> Optional[int]:
    if isinstance(raw_item_id, int):
        return raw_item_id
    text = str(raw_item_id or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return resolve_item_id(conn, text)
    except (LookupError, TypeError, ValueError):
        return None


def _checkpoint_for_envelope(envelope: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    checkpoint = envelope.get("chain_checkpoint")
    return dict(checkpoint) if isinstance(checkpoint, Mapping) else None


def _read_envelope(raw_envelope: Any) -> dict[str, Any]:
    if not raw_envelope:
        return {}
    try:
        envelope = json.loads(str(raw_envelope))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return dict(envelope) if isinstance(envelope, Mapping) else {}


def consume_terminal_item_checkpoint(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    terminal_status: str,
) -> bool:
    """Mark one matching, chainable checkpoint as consumed without committing."""
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id={_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    envelope = _read_envelope(row["offer_envelope"])
    checkpoint = _checkpoint_for_envelope(envelope)
    if checkpoint is None or not bool(checkpoint.get("chainable")):
        return False
    if _resolved_item_id(conn, checkpoint.get("item_id")) != int(item_id):
        return False
    if checkpoint.get("handler_outcome") == OUTCOME_TERMINAL_ITEM_CLOSED:
        return False

    completed_at = _now_iso()
    checkpoint.update(
        {
            "handler_outcome": OUTCOME_TERMINAL_ITEM_CLOSED,
            "chain_summary_label": TERMINAL_ITEM_CLOSED_LABEL,
            "status": terminal_status,
            "completed_at": completed_at,
        }
    )
    envelope["chain_checkpoint"] = checkpoint
    conn.execute(
        f"UPDATE harness_sessions SET offer_envelope={_p(conn)} "
        f"WHERE session_id={_p(conn)}",
        (json.dumps(envelope), session_id),
    )
    try:
        step = int(checkpoint.get("step", 0) or 0)
    except (TypeError, ValueError):
        step = 0
    stamp_chain_checkpoint(
        conn,
        session_id=session_id,
        step=step,
        at=completed_at,
    )
    return True


def preserve_consumed_terminal_outcome(
    conn: Any,
    *,
    previous_checkpoint: Any,
    item_id: Any,
    chainable: bool,
    handler_outcome: str,
    chain_summary_label: Optional[str],
) -> tuple[str, Optional[str]]:
    """Keep closeout consumption across the same handler's final checkpoint."""
    if not chainable or handler_outcome != "completed":
        return handler_outcome, chain_summary_label
    if not isinstance(previous_checkpoint, Mapping):
        return handler_outcome, chain_summary_label
    if previous_checkpoint.get("handler_outcome") != OUTCOME_TERMINAL_ITEM_CLOSED:
        return handler_outcome, chain_summary_label
    previous_item = _resolved_item_id(conn, previous_checkpoint.get("item_id"))
    current_item = _resolved_item_id(conn, item_id)
    if previous_item is None or previous_item != current_item:
        return handler_outcome, chain_summary_label
    return OUTCOME_TERMINAL_ITEM_CLOSED, TERMINAL_ITEM_CLOSED_LABEL


def close_terminal_item_sessions(
    conn: Any,
    *,
    item_id: int,
    terminal_status: str,
    holder_session_ids: Iterable[str],
    commit: bool = True,
) -> TerminalItemSessionCloseout:
    """Release terminal-item focus and consume its checkpoint under one lock."""
    from .sessions_claim_lifecycle_lock import (
        lock_session_rows_for_claim_lifecycle,
    )
    from .sessions_render_attribution import release_item_focus_if_current

    session_ids = tuple(
        sorted({str(value) for value in holder_session_ids if str(value)})
    )
    if not session_ids:
        if commit:
            conn.commit()
        return TerminalItemSessionCloseout()

    session_rows = lock_session_rows_for_claim_lifecycle(conn, session_ids)
    live_session_ids = tuple(
        session_id
        for session_id in session_ids
        if session_id in session_rows and session_rows[session_id] is None
    )
    focus_released = tuple(
        session_id
        for session_id in live_session_ids
        if release_item_focus_if_current(conn, session_id, item_id)
    )
    checkpoint_consumed = tuple(
        session_id
        for session_id in live_session_ids
        if consume_terminal_item_checkpoint(
            conn,
            session_id=session_id,
            item_id=int(item_id),
            terminal_status=terminal_status,
        )
    )
    if commit:
        conn.commit()
    return TerminalItemSessionCloseout(
        focus_released=focus_released,
        checkpoint_consumed=checkpoint_consumed,
    )


__all__ = [
    "OUTCOME_TERMINAL_ITEM_CLOSED",
    "TERMINAL_ITEM_CLOSED_LABEL",
    "TerminalItemSessionCloseout",
    "close_terminal_item_sessions",
    "consume_terminal_item_checkpoint",
    "preserve_consumed_terminal_outcome",
]
