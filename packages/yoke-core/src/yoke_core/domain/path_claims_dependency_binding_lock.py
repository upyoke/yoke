"""Workflow-binding locks for downstream path-claim propagation."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain import db_backend


def lock_candidate_item_bindings(
    conn: Any,
    candidate_claim_ids: Iterable[int],
) -> None:
    """Lock owning-item bindings before downstream claims are reclassified."""
    claim_ids = tuple(int(claim_id) for claim_id in candidate_claim_ids)
    if not claim_ids:
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in claim_ids)
    rows = conn.execute(
        f"SELECT id, item_id FROM path_claims WHERE id IN ({placeholders}) ORDER BY id",
        claim_ids,
    ).fetchall()

    from yoke_core.domain.workflow_item_binding_lock import (
        lock_item_workflow_bindings,
    )

    lock_item_workflow_bindings(
        conn,
        (int(row[1]) for row in rows if row[1] is not None),
    )


__all__ = ["lock_candidate_item_bindings"]
