"""Stage-level successor handoffs and their released-predecessor admission."""

from __future__ import annotations

import shlex
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from yoke_contracts.api.function_call import FunctionWarning
from yoke_core.domain.project_identity import placeholder, render_item_ref
from yoke_core.domain.workflow_stage_levels import item_stage_level
from yoke_core.domain.work_claim_target_sql import scope_int_sql

_CAPTURE: ContextVar[list[dict[str, str]] | None] = ContextVar(
    "level_handoff_capture", default=None
)


@contextmanager
def capture_level_handoffs():
    """Propagate a transition handoff through a composed merge ceremony."""
    existing = _CAPTURE.get()
    if existing is not None:
        yield existing
        return
    captured: list[dict[str, str]] = []
    token = _CAPTURE.set(captured)
    try:
        yield captured
    finally:
        _CAPTURE.reset(token)


def record_level_handoff(result: dict[str, Any]) -> None:
    handoff = result.get("handoff")
    captured = _CAPTURE.get()
    if captured is not None and handoff:
        captured.append(dict(handoff))


def level_handoff(
    conn: Any, *, item_id: int, session_id: str | None, stage_id: str
) -> dict[str, str] | None:
    """Compare the target effective level with the registered worker's level."""
    if not session_id:
        return None
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT execution_level FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return None
    resolved = item_stage_level(conn, item_id, stage_id=stage_id)
    if resolved is None or resolved["level"] == row[0]:
        return None
    project = conn.execute(
        f"SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id WHERE i.id={p}",
        (int(item_id),),
    ).fetchone()[0]
    ref = render_item_ref(conn, item_id, required=True)
    command = (
        f"yoke session-control launch create --project {shlex.quote(str(project))} "
        f"--item {ref} --idempotency-key {shlex.quote(f'level-successor:{item_id}:{session_id}:{stage_id}')}"
    )
    return {
        "reason": "level_change",
        "stage_id": stage_id,
        "level": resolved["level"],
        "next_command": command,
    }


def item_level_handoff(
    item_id: int, session_id: str | None, stage_id: str
) -> tuple[dict[str, str] | None, list[FunctionWarning]]:
    """A post-commit read failure is a named warning, never a failed write."""
    from yoke_core.domain.db_helpers import connect

    try:
        with connect() as conn:
            return level_handoff(
                conn, item_id=item_id, session_id=session_id, stage_id=stage_id
            ), []
    except Exception as exc:  # noqa: BLE001 - transition already committed
        return None, [
            FunctionWarning(
                code="level_handoff_unread",
                step="level_handoff",
                detail=f"Transition committed, but stage-level handoff could not be read ({exc}). Recovery: read the item and worker levels before continuing.",
            )
        ]


def released_level_predecessor(
    conn: Any, *, item_id: int, session_id: str | None, level: str | None
) -> str | None:
    """Admit only the latest holder, after releasing every claim, for its own successor."""
    if not session_id:
        return None
    p = placeholder(conn)
    scope = scope_int_sql(conn, "scope", "item_id")
    latest = conn.execute(
        f"SELECT session_id, released_at FROM work_claims WHERE target_kind='item' "
        f"AND claim_type='exclusive' AND {scope}={p} ORDER BY claimed_at DESC, id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if latest is None or latest[0] != session_id or latest[1] is None:
        return None
    if conn.execute(
        f"SELECT 1 FROM work_claims WHERE session_id={p} AND released_at IS NULL LIMIT 1",
        (session_id,),
    ).fetchone():
        return None
    row = conn.execute(
        f"SELECT status FROM items WHERE id={p}", (int(item_id),)
    ).fetchone()
    handoff = level_handoff(
        conn, item_id=item_id, session_id=session_id, stage_id=str(row[0])
    )
    return session_id if handoff and handoff["level"] == level else None


__all__ = ["item_level_handoff", "level_handoff", "released_level_predecessor"]
