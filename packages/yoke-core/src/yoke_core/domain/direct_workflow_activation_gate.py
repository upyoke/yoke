"""Activation gates shared by the Blitz and Dash workflow interpreters."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    validate_item_worktree_roles,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimConflictError,
    StrategyExecutionError,
    acquire_strategy_doc_claim,
    active_strategy_doc_claim,
)
from yoke_core.domain.work_claim_targets import scope_int_sql
from yoke_core.domain.workflow_behavior import worktree_lane_policy
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _failure(code: str, message: str, hint: str) -> dict:
    return {
        "success": False,
        "error_code": code,
        "error": message,
        "remediation_hint": hint,
    }


def _activation_prerequisites(
    conn: Any,
    *,
    item_id: int,
    session_id: Optional[str],
    gate_name: str,
) -> Optional[dict]:
    """Require this session's live item claim and a policy-valid worktree."""
    clean_session = str(session_id or "").strip()
    code = f"GATE_{gate_name}_UNSATISFIED"
    if not clean_session:
        return _failure(
            code,
            "Direct-workflow activation requires the executing session id.",
            "Acquire the item work claim and retry from that session.",
        )
    marker = _marker(conn)
    item_scope = scope_int_sql(conn, "scope", "item_id")
    claim = conn.execute(
        "SELECT session_id FROM work_claims "
        "WHERE target_kind = 'item' "
        f"AND {item_scope} = {marker} AND released_at IS NULL "
        "ORDER BY claimed_at DESC, id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    holder = (
        None
        if claim is None
        else str(claim["session_id"] if hasattr(claim, "keys") else claim[0])
    )
    if holder != clean_session:
        detail = (
            "has no active item work claim"
            if holder is None
            else (f"is claimed by session {holder!r}")
        )
        return _failure(
            code,
            f"Item {item_id} {detail}; activation belongs to "
            f"session {clean_session!r}.",
            "Acquire the item work claim or coordinate with its holder.",
        )
    # A workflow that requires no lane has nothing further to activate: the
    # work claim above is the whole gate, and the item never gets a worktree.
    runtime = load_item_workflow_runtime(conn, int(item_id))
    if not worktree_lane_policy(runtime).required_roles:
        return None
    if not _table_exists(conn, "item_worktrees"):
        return _failure(
            code,
            f"Item {item_id} has no universal worktree registry.",
            "Prepare the direct-workflow worktree before activation.",
        )
    lanes = list_item_worktrees(conn, int(item_id), active_only=True)
    if not lanes:
        return _failure(
            code,
            f"Item {item_id} has no active registered worktree lane.",
            "Prepare the direct-workflow worktree before activation.",
        )
    try:
        validate_item_worktree_roles(conn, int(item_id))
    except ValueError as exc:
        return _failure(
            code,
            str(exc),
            "Reconcile the registered lanes with the pinned workflow policy.",
        )
    if any(not str(lane.get("path") or "").strip() for lane in lanes):
        return _failure(
            code,
            f"Item {item_id} has a registered lane without a worktree path.",
            "Create or reuse every registered lane before activation.",
        )
    return None


def evaluate_work_claim_activation(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str],
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Require the real Dash item claim and implementation worktree."""
    gate_conn = conn if conn is not None else connect(db_path)
    try:
        return _activation_prerequisites(
            gate_conn,
            item_id=item_id,
            session_id=session_id,
            gate_name="WORK_CLAIM_ACTIVATION",
        )
    finally:
        if conn is None:
            gate_conn.close()


def evaluate_doc_claim_activation(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str],
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Acquire the linked Blitz document after activation prerequisites pass."""
    gate_conn = conn if conn is not None else connect(db_path)
    try:
        blocked = _activation_prerequisites(
            gate_conn,
            item_id=item_id,
            session_id=session_id,
            gate_name="DOC_CLAIM_ACTIVATION",
        )
        if blocked is not None:
            return blocked
        existing = active_strategy_doc_claim(gate_conn, item_id=int(item_id))
        if existing is not None:
            return None
        marker = _marker(conn)
        actor_row = gate_conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
            (str(session_id),),
        ).fetchone()
        actor_id = (
            None
            if actor_row is None
            else (actor_row["actor_id"] if hasattr(actor_row, "keys") else actor_row[0])
        )
        acquire_strategy_doc_claim(
            gate_conn,
            item_id=int(item_id),
            session_id=str(session_id),
            actor_id=None if actor_id is None else int(actor_id),
            commit=conn is None,
        )
        return None
    except StrategyDocClaimConflictError as exc:
        return _failure(
            "GATE_DOC_CLAIM_ACTIVATION_CONFLICT",
            str(exc),
            "Coordinate with the owning item or wait for its lifecycle release.",
        )
    except StrategyExecutionError as exc:
        return _failure(
            "GATE_DOC_CLAIM_ACTIVATION_UNSATISFIED",
            str(exc),
            "Link one execution document and prepare the Blitz worktree.",
        )
    finally:
        if conn is None:
            gate_conn.close()


__all__ = [
    "evaluate_doc_claim_activation",
    "evaluate_work_claim_activation",
]
