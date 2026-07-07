"""Shared chain-pending state helper consumed by both end paths.

The CHAIN_PENDING guard in :mod:`yoke_core.domain.sessions_render_end`
and the ``chain_pending`` decline branch in
:func:`sessions_render_end.end_session_if_empty` both consume the
chainable-checkpoint snapshot computed here. Sharing the helper means a
future change to "what counts as chain-pending" lands in one place.

Sibling of ``sessions_render_end`` because that module's authored size
otherwise crosses the 350-line limit; the dataclass plus three small
helpers move out cleanly with no cross-cutting state.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from .sessions_handler_outcome import NON_USEFUL_STEP_OUTCOMES, OUTCOME_COMPLETED
from .sessions_queries import normalize_claim_item_id, read_chain_checkpoint


_DEFAULT_MAX_CHAIN_STEPS = 3
_CHAIN_PENDING_OUTCOMES = frozenset({OUTCOME_COMPLETED, *NON_USEFUL_STEP_OUTCOMES})


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class ChainPendingState:
    """Chainable-checkpoint snapshot computed once per end attempt.

    ``pending`` is the structural verdict: the session has a chainable
    checkpoint within budget. ``end_session`` and ``end_session_if_empty``
    both consume this field; the other fields populate audit events
    (``ChainDeclineOverridden`` for the explicit override path,
    ``ChainEndDeferred`` for the Stop-hook decline path).
    """

    pending: bool
    step: int
    max_chain_steps: int
    chainable: bool
    handler_outcome: Optional[str]
    action: Optional[str]
    item_id: Optional[str]


def chain_pending_state(
    conn: Any,
    session_id: str,
) -> ChainPendingState:
    """Read the persisted chain checkpoint and decide whether the session is pending."""
    checkpoint = read_chain_checkpoint(conn, session_id)
    if checkpoint is None:
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

    max_steps = _DEFAULT_MAX_CHAIN_STEPS
    envelope_row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if envelope_row and envelope_row["offer_envelope"]:
        try:
            env = json.loads(envelope_row["offer_envelope"])
            max_steps = int(env.get("max_chain_steps", _DEFAULT_MAX_CHAIN_STEPS))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    pending = chainable and step < max_steps and is_chain_pending_outcome(
        handler_outcome,
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


def next_offer_step(state: ChainPendingState) -> int:
    """Return the next ``session-offer`` step using normal chain accounting."""
    if state.handler_outcome in NON_USEFUL_STEP_OUTCOMES:
        return state.step
    return state.step + 1


def next_action_command(conn, session_id: str, next_step: int) -> str:
    """Canonical resume command echoed on the chain-pending JSON output.

    The Stop hook returns this string so an inspecting agent (or the
    operator) can resume the chain without rederiving the loop.md Step A
    invocation.
    """
    row = conn.execute(
        f"""SELECT executor, provider, workspace, execution_lane
           FROM harness_sessions
           WHERE session_id = {_p(conn)}""",
        (session_id,),
    ).fetchone()
    if row is None:
        return (
            "python3 -m yoke_core.api.service_client session-offer "
            f"--session-id {shlex.quote(session_id)} --step {next_step}"
        )

    # ``--model`` is intentionally omitted: ``session-offer`` resolves the
    # canonical model from ``harness_sessions.model`` (or the
    # ``hook_helpers_model.detect_model`` fallback) using ``--session-id``,
    # so echoing the model here would just round-trip the same value back
    # to the same row.
    parts = [
        "python3",
        "-m",
        "yoke_core.api.service_client",
        "session-offer",
        "--executor",
        row["executor"],
        "--provider",
        row["provider"],
        "--workspace",
        row["workspace"],
    ]
    if row["execution_lane"]:
        parts.extend(["--lane", row["execution_lane"]])
    parts.extend(["--session-id", session_id, "--step", str(next_step)])
    return " ".join(shlex.quote(str(part)) for part in parts)


def is_chain_pending_outcome(handler_outcome: Optional[str]) -> bool:
    """Whether a handler outcome is allowed to keep the chain alive."""
    return handler_outcome in _CHAIN_PENDING_OUTCOMES


def chain_pending_outcomes() -> frozenset[str]:
    """Expose the canonical outcome set for tests and future callers."""
    return _CHAIN_PENDING_OUTCOMES


__all__ = [
    "ChainPendingState",
    "chain_pending_state",
    "chain_pending_outcomes",
    "is_chain_pending_outcome",
    "last_released_at",
    "next_action_command",
    "next_offer_step",
]
