"""DB helpers for worktree creation."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, Tuple

from yoke_contracts.api.function_call import TargetRef


def item_worktree_authority_is_https() -> bool:
    """Return whether lane authority is reached through the HTTPS relay."""
    try:
        from yoke_cli.config import machine_config

        connection = machine_config.active_connection()
    except Exception:
        return False
    return bool(
        connection
        and str(connection.get("transport") or "") == "https"
    )


def _response_error(response: Any) -> str:
    error = getattr(response, "error", None)
    if error is None:
        return "registered item-worktree operation failed"
    code = str(getattr(error, "code", "") or "operation_failed")
    message = str(getattr(error, "message", "") or "request failed")
    return f"{code}: {message}"


def prepare_authoritative_item_worktrees(item_id: int) -> list[dict[str, Any]]:
    """Ensure the remote default lane and list every active authoritative lane."""
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    target = TargetRef(kind="item", item_id=int(item_id))
    prepared = call_dispatcher(
        function_id="item_worktrees.create",
        target=target,
        payload={},
    )
    if not prepared.success:
        raise RuntimeError(_response_error(prepared))
    listed = call_dispatcher(
        function_id="item_worktrees.list",
        target=target,
        payload={},
    )
    if not listed.success:
        raise RuntimeError(_response_error(listed))
    rows = (listed.result or {}).get("worktrees")
    if not isinstance(rows, list):
        raise RuntimeError("item_worktrees.list returned no worktrees list")
    return [dict(row) for row in rows if isinstance(row, dict)]


def persist_item_worktrees(
    item_id: int,
    lanes: Iterable[Tuple[Any, ...]],
    db_path: Optional[str],
) -> None:
    """Persist the universal lane rows provisioned by worktree creation."""
    from yoke_core.domain.db_helpers import connect

    lane_rows = list(lanes)
    if not lane_rows:
        return
    if db_path is None and item_worktree_authority_is_https():
        _record_authoritative_item_worktree_paths(item_id, lane_rows)
        return
    if db_path is None and all(
        len(raw) == 4 and raw[0] is None for raw in lane_rows
    ):
        # Compatibility fallback for an item number with no registry row:
        # provision the conventional lane locally, but do not invent remote
        # authority for it.
        return
    conn = connect(db_path)
    try:
        from yoke_core.domain.item_worktrees import record_item_worktree

        for raw in lane_rows:
            if len(raw) == 3:
                branch, path, lane_role = raw
            elif len(raw) == 4:
                _lane_id, branch, path, lane_role = raw
            else:
                raise ValueError(f"malformed item worktree lane: {raw!r}")
            record_item_worktree(
                conn,
                item_id=int(item_id),
                branch=branch,
                path=path,
                lane_role=lane_role,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_authoritative_item_worktree_paths(
    item_id: int,
    lanes: Sequence[Tuple[Any, ...]],
) -> None:
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    target = TargetRef(kind="item", item_id=int(item_id))
    for raw in lanes:
        if len(raw) != 4:
            raise ValueError(
                "hosted item worktree persistence requires lane id, branch, "
                f"path, and role; got {raw!r}"
            )
        lane_id, branch, path, _lane_role = raw
        if lane_id is None:
            raise ValueError(
                f"hosted item worktree branch {branch!r} has no authoritative id"
            )
        response = call_dispatcher(
            function_id="item_worktrees.path_record",
            target=target,
            payload={"path": str(path)},
            preconditions={
                "worktree_id": int(lane_id),
                "branch": str(branch),
            },
        )
        if not response.success:
            raise RuntimeError(_response_error(response))


def check_path_claim_gate(item_id: int, db_path: Optional[str]) -> Optional[str]:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims_gate import (
        PathClaimGateBlocked,
        check_worktree_create_gate,
    )

    gate_conn = connect(db_path)
    try:
        check_worktree_create_gate(gate_conn, int(item_id))
    except PathClaimGateBlocked as exc:
        return str(exc)
    finally:
        gate_conn.close()
    return None


__all__ = [
    "check_path_claim_gate",
    "item_worktree_authority_is_https",
    "persist_item_worktrees",
    "prepare_authoritative_item_worktrees",
]
