"""Reuse and cleanup helpers for item-facing path-claim registration."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import PathClaimError


_NON_TERMINAL_STATES = ("planned", "blocked", "active")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class MultipleConcreteClaims(PathClaimError):
    """Registration found ambiguous existing concrete claim lineage."""


def reuse_existing_concrete_claim(
    conn: Any,
    *,
    item_id: int,
    integration_target: str,
    target_ids: Sequence[int],
    project_id: str,
    commit: bool = True,
    emit_event: bool = True,
) -> Optional[int]:
    """Widen the existing concrete claim instead of minting a sibling."""
    claim_ids = _existing_concrete_claim_ids(
        conn,
        item_id=item_id,
        integration_target=integration_target,
    )
    if not claim_ids:
        return None
    if len(claim_ids) > 1:
        raise MultipleConcreteClaims(
            f"item YOK-{item_id} already has multiple non-terminal "
            f"concrete claims on {integration_target!r}: {claim_ids}; "
            "narrow/cancel the duplicate lineages before registering more"
        )
    claim_id = claim_ids[0]
    from yoke_core.domain import path_claims_events as _events
    from yoke_core.domain.path_claims import get_claim
    from yoke_core.domain.path_claims_amend import widen

    reason = "registration reused existing concrete path claim"
    amendment_id = widen(
        conn,
        claim_id=claim_id,
        add_target_ids=target_ids,
        reason=reason,
        commit=commit,
    )
    if emit_event:
        _events.emit_amended(
            conn=conn,
            claim=get_claim(conn, claim_id),
            amendment_id=amendment_id,
            amendment_kind="widen",
            payload={"added": list(target_ids)},
            reason=reason,
            project=project_id,
        )
    return claim_id


def cancel_superseded_exceptions(
    conn: Any,
    *,
    item_id: int,
    integration_target: str,
    replacement_claim_id: int,
    project_id: str,
    task_num: Optional[int] = None,
    commit: bool = True,
    emit_event: bool = True,
) -> list[int]:
    """Cancel no-claim exceptions once concrete coverage exists."""
    marker = _p(conn)
    placeholders = ",".join(marker for _ in _NON_TERMINAL_STATES)
    join = (
        "JOIN path_claim_task_bindings b ON b.claim_id = path_claims.id "
        if task_num is not None
        else ""
    )
    task_filter = (
        f"AND b.epic_id = {marker} AND b.task_num = {marker} "
        if task_num is not None
        else ""
    )
    task_params = (item_id, int(task_num)) if task_num is not None else ()
    rows = conn.execute(
        "SELECT path_claims.id FROM path_claims "
        f"{join}"
        f"WHERE path_claims.item_id = {marker} "
        f"AND path_claims.integration_target = {marker} "
        "AND mode = 'exception' "
        f"AND state IN ({placeholders}) "
        f"{task_filter}"
        f"AND path_claims.id <> {marker} "
        "ORDER BY path_claims.id",
        (
            item_id,
            integration_target,
            *_NON_TERMINAL_STATES,
            *task_params,
            replacement_claim_id,
        ),
    ).fetchall()
    if not rows:
        return []
    from yoke_core.domain import path_claims_events as _events
    from yoke_core.domain.path_claims import cancel as cancel_claim, get_claim

    reason = f"superseded by concrete path claim {replacement_claim_id}"
    cancelled: list[int] = []
    for row in rows:
        claim_id = int(row[0])
        cancel_claim(
            conn,
            claim_id=claim_id,
            reason=reason,
            commit=commit,
        )
        if emit_event:
            _events.emit_cancelled(
                conn=conn,
                claim=get_claim(conn, claim_id),
                reason=reason,
                project=project_id,
            )
        cancelled.append(claim_id)
    return cancelled


def _existing_concrete_claim_ids(
    conn: Any,
    *,
    item_id: int,
    integration_target: str,
) -> list[int]:
    marker = _p(conn)
    placeholders = ",".join(marker for _ in _NON_TERMINAL_STATES)
    rows = conn.execute(
        "SELECT id FROM path_claims "
        f"WHERE item_id = {marker} AND integration_target = {marker} "
        "AND mode <> 'exception' "
        f"AND state IN ({placeholders}) "
        "ORDER BY id",
        (item_id, integration_target, *_NON_TERMINAL_STATES),
    ).fetchall()
    return [int(row[0]) for row in rows]


__all__ = [
    "MultipleConcreteClaims",
    "cancel_superseded_exceptions",
    "reuse_existing_concrete_claim",
]
