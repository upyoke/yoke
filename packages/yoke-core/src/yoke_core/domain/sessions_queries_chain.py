"""Session chain checkpoint persistence."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_CHAIN_STEP_COMPLETED, SessionError
from .sessions_queries_base import _now_iso


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def update_chain_checkpoint(
    conn: Any,
    session_id: str,
    *,
    step: int,
    action: str,
    chainable: bool,
    handler_outcome: str = "completed",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    status: Optional[str] = None,
    required_path: Optional[str] = None,
    pre_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a post-handler chain checkpoint on the session's offer_envelope.

    Called after a mode handler returns to record the handler outcome so that
    the re-offer decision can consult persisted state rather than
    prompt-local variables when deciding whether to re-offer.

    Also emits a ``ChainStepCompleted`` event for telemetry.

    Returns the checkpoint dict that was written.
    """
    now = _now_iso()

    row = conn.execute(
        f"SELECT ended_at, offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row["ended_at"] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    # Parse existing envelope (may be None on first call)
    existing_envelope: Dict[str, Any] = {}
    if row["offer_envelope"]:
        try:
            existing_envelope = json.loads(row["offer_envelope"])
        except (json.JSONDecodeError, TypeError):
            pass

    checkpoint: Dict[str, Any] = {
        "step": step,
        "action": action,
        "chainable": chainable,
        "handler_outcome": handler_outcome,
        "completed_at": now,
    }
    if item_id:
        checkpoint["item_id"] = item_id
    if task_num is not None:
        checkpoint["task_num"] = task_num
    if status:
        checkpoint["status"] = status
    if required_path:
        checkpoint["required_path"] = required_path
    if pre_status:
        checkpoint["pre_status"] = pre_status

    existing_envelope["chain_checkpoint"] = checkpoint
    envelope_json = json.dumps(existing_envelope)

    conn.execute(
        f"UPDATE harness_sessions SET offer_envelope = {_p(conn)} "
        f"WHERE session_id = {_p(conn)}",
        (envelope_json, session_id),
    )
    # Chain progress is first-class session state: unlike the
    # offer_envelope checkpoint (clobbered by later offers), these columns
    # survive re-offers and are what the stuck-chain doctor HC reads.
    from .claim_chain_state import stamp_chain_checkpoint

    stamp_chain_checkpoint(conn, session_id=session_id, step=step, at=now)
    conn.commit()

    # Emit ChainStepCompleted event
    event_ctx: Dict[str, Any] = {
        "session_id": session_id,
        "step": step,
        "action": action,
        "chainable": chainable,
        "handler_outcome": handler_outcome,
    }
    if item_id:
        event_ctx["item_id"] = item_id
    if task_num is not None:
        event_ctx["task_num"] = task_num

    _sa._emit_event(
        EVENT_CHAIN_STEP_COMPLETED,
        event_kind="workflow",
        event_type="chain_checkpoint",
        source_type="backend",
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        context=event_ctx,
        severity="STATUS",
    )

    return checkpoint


def read_chain_checkpoint(
    conn: Any,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Read the persisted chain checkpoint from a session's offer_envelope.

    Returns the checkpoint dict if present, or None.
    """
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    if not row["offer_envelope"]:
        return None
    try:
        envelope = json.loads(row["offer_envelope"])
    except (json.JSONDecodeError, TypeError):
        return None
    return envelope.get("chain_checkpoint")


def read_chain_skip_memory(
    conn: Any,
    session_id: str,
) -> list[Dict[str, Any]]:
    """Return the within-chain skip-memory entries persisted on the envelope.

    Each entry is a dict carrying at minimum ``item_id`` and ``skip_reason``.
    The list is empty when the session has no envelope or no entries yet.
    The memory is per-chain — `/yoke do` loops should clear it via the
    same envelope path between chains; the offer flow only appends and reads.
    """
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None or not row["offer_envelope"]:
        return []
    try:
        envelope = json.loads(row["offer_envelope"])
    except (json.JSONDecodeError, TypeError):
        return []
    raw = envelope.get("chain_skip_memory", [])
    if not isinstance(raw, list):
        return []
    return [dict(entry) for entry in raw if isinstance(entry, dict)]


def append_chain_skip_entry(
    conn: Any,
    session_id: str,
    entry: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Append a single skip entry to the chain skip memory and persist.

    The entry shape is dict-shaped so callers can record
    item_id, skip_reason, current_status / expected_status, claim
    holder context, process_key, and chain_step in one envelope write.
    Entries with falsy ``item_id`` AND falsy ``process_key`` are
    skipped — there is nothing to deduplicate against.

    Returns the updated memory list.
    """
    if not entry.get("item_id") and not entry.get("process_key"):
        return read_chain_skip_memory(conn, session_id)
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return []
    envelope: Dict[str, Any] = {}
    # Index-access works for both native tuple rows and mapping-style rows,
    # keeping the helper safe for inline-Python callers documented in
    # .agents/skills/yoke/do/loop-routing.md.
    raw_envelope = row[0]
    if raw_envelope:
        try:
            envelope = json.loads(raw_envelope)
        except (json.JSONDecodeError, TypeError):
            envelope = {}
    raw_memory = envelope.get("chain_skip_memory", [])
    memory: list[Dict[str, Any]] = (
        [dict(e) for e in raw_memory if isinstance(e, dict)]
        if isinstance(raw_memory, list)
        else []
    )
    memory.append(dict(entry))
    envelope["chain_skip_memory"] = memory
    conn.execute(
        f"UPDATE harness_sessions SET offer_envelope = {_p(conn)} "
        f"WHERE session_id = {_p(conn)}",
        (json.dumps(envelope), session_id),
    )
    conn.commit()
    return memory
