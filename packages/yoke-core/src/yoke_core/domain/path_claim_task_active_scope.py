"""Per-task narrowing shared by live path-claim enforcement surfaces."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple


Target = Tuple[str, str]


def _item_id(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _task_policy(conn: Any, item_id: int) -> bool | None:
    from yoke_core.domain.path_claim_task_bindings import (
        pinned_task_claim_policy,
    )

    return pinned_task_claim_policy(conn, item_id)


def effective_targets_for_claim_session(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    target_path: str,
    cwd: str,
    parent_targets: Sequence[Target],
) -> list[Target]:
    """Return parent coverage or the physical lane's task-budget union."""
    try:
        task_scoped = _task_policy(conn, item_id)
    except Exception:
        return []
    if not task_scoped:
        return list(parent_targets)
    try:
        from yoke_core.domain.path_claim_task_session_coverage import (
            effective_targets_for_session,
        )

        return list(
            effective_targets_for_session(
                conn,
                session_id=session_id,
                item_id=item_id,
                target_path=target_path,
                cwd=cwd,
            )
        )
    except Exception:
        return []


def scope_injected_claim_for_target(
    conn: Any,
    *,
    claim: Dict[str, Any],
    session_id: str,
    target_path: str,
    cwd: str,
) -> Optional[Dict[str, Any]]:
    """Keep injected seams from bypassing a real per-task workflow pin."""
    item_id = _item_id(claim.get("owner_item_id"))
    if item_id is None:
        return claim
    try:
        task_scoped = _task_policy(conn, item_id)
    except Exception:
        task_scoped = True
    if not task_scoped:
        return claim
    from yoke_core.domain.path_claim_active_claim_lookup import (
        resolve_active_claim_for_session,
    )

    live = resolve_active_claim_for_session(
        session_id=session_id,
        conn=conn,
        target_path=target_path,
        cwd=cwd,
    )
    if live is not None:
        return live
    narrowed = dict(claim)
    narrowed["covered_paths"] = []
    narrowed["covered_target_kinds"] = []
    return narrowed


def resolve_claim_scope_for_target(
    *,
    conn: Any,
    claim: Optional[Dict[str, Any]],
    session_id: str,
    target_path: str,
    cwd: str,
    resolver: Any,
) -> Optional[Dict[str, Any]]:
    """Resolve one target's effective claim, honoring injected test seams."""
    if claim is not None and conn is not None:
        return scope_injected_claim_for_target(
            conn,
            claim=claim,
            session_id=session_id,
            target_path=target_path,
            cwd=cwd,
        )
    if claim is not None:
        return claim
    return resolver(
        session_id=session_id,
        conn=conn,
        target_path=target_path,
        cwd=cwd,
    )


__all__ = [
    "effective_targets_for_claim_session",
    "resolve_claim_scope_for_target",
    "scope_injected_claim_for_target",
]
