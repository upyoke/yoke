"""Serialize host-control submissions on their durable lease row."""

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_record import (
    FROM_CLAUSE,
    SELECT_COLUMNS,
    CoordinationClaim,
    row_to_claim,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimNotFoundError,
    get_claim,
)


def lock_submission_claim(conn: Any, claim_id: int) -> CoordinationClaim:
    if not db_backend.connection_is_postgres(conn):
        if not bool(getattr(conn, "in_transaction", False)):
            conn.execute("BEGIN IMMEDIATE")
        return get_claim(conn, claim_id)
    marker = "%s"
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} WHERE wc.id={marker} FOR UPDATE OF wc",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise CoordinationClaimNotFoundError(
            f"Coordination claim id={claim_id} not found"
        )
    return row_to_claim(row)
