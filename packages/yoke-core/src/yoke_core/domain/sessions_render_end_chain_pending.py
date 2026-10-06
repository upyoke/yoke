"""Stored checkpoint projection for unfinished-work telemetry."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from .sessions_handler_outcome import NON_USEFUL_STEP_OUTCOMES, OUTCOME_COMPLETED
from .sessions_queries import normalize_claim_item_id


_DEFAULT_MAX_CHAIN_STEPS = 3
_CHAIN_PENDING_OUTCOMES = frozenset({OUTCOME_COMPLETED, *NON_USEFUL_STEP_OUTCOMES})


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class ChainPendingState:
    """Checkpoint telemetry facts; these do not authorize ending."""

    pending: bool
    step: int
    max_chain_steps: int
    chainable: bool
    handler_outcome: Optional[str]
    action: Optional[str]
    item_id: Optional[str]


def chain_pending_state_from_envelope(envelope: Any) -> ChainPendingState:
    """Decide chain-pending state from a stored offer-envelope value."""
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except (json.JSONDecodeError, TypeError):
            envelope = None
    if not isinstance(envelope, Mapping):
        envelope = {}
    checkpoint = envelope.get("chain_checkpoint")
    if not isinstance(checkpoint, Mapping):
        return ChainPendingState(
            pending=False,
            step=0,
            max_chain_steps=_DEFAULT_MAX_CHAIN_STEPS,
            chainable=False,
            handler_outcome=None,
            action=None,
            item_id=None,
        )

    step = int(checkpoint.get("step", 0) or 0)
    chainable = bool(checkpoint.get("chainable", False))
    handler_outcome = checkpoint.get("handler_outcome")
    action = checkpoint.get("action")
    item_id = checkpoint.get("item_id")

    try:
        max_steps = int(envelope.get("max_chain_steps", _DEFAULT_MAX_CHAIN_STEPS))
    except (TypeError, ValueError):
        max_steps = _DEFAULT_MAX_CHAIN_STEPS

    pending = (
        chainable
        and step < max_steps
        and is_chain_pending_outcome(
            handler_outcome,
        )
    )

    return ChainPendingState(
        pending=pending,
        step=step,
        max_chain_steps=max_steps,
        chainable=chainable,
        handler_outcome=handler_outcome,
        action=action,
        item_id=(
            normalize_claim_item_id(str(item_id)) if item_id is not None else None
        ),
    )


def chain_pending_state(
    conn: Any,
    session_id: str,
) -> ChainPendingState:
    """Read the persisted chain checkpoint and decide whether the session is pending."""
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    return chain_pending_state_from_envelope(
        row["offer_envelope"] if row is not None else None,
    )


def last_released_at(
    conn: Any,
    session_id: str,
) -> Optional[str]:
    """Most recent ``work_claims.released_at`` for the session, or None."""
    row = conn.execute(
        f"""SELECT released_at FROM work_claims
           WHERE session_id = {_p(conn)} AND released_at IS NOT NULL
           ORDER BY released_at DESC, id DESC
           LIMIT 1""",
        (session_id,),
    ).fetchone()
    if row is None or not row["released_at"]:
        return None
    return str(row["released_at"])


def is_chain_pending_outcome(handler_outcome: Optional[str]) -> bool:
    """Whether a handler outcome is allowed to keep the chain alive."""
    return handler_outcome in _CHAIN_PENDING_OUTCOMES


def chain_pending_outcomes() -> frozenset[str]:
    """Expose the canonical outcome set for tests and future callers."""
    return _CHAIN_PENDING_OUTCOMES


__all__ = [
    "ChainPendingState",
    "chain_pending_state",
    "chain_pending_state_from_envelope",
    "chain_pending_outcomes",
    "is_chain_pending_outcome",
    "last_released_at",
]
