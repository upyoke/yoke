"""Remove the stored steering-seat to document-lock column and its index."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0027_pair_steering_document_claims",)
TABLE = "strategy_doc_claims"
RETIRED_COLUMN = "paired_work_claim_id"
RETIRED_INDEX = "uq_strategy_doc_claims_paired_work_claim"


def apply(conn: Any) -> None:
    """Drop the retired pair index and column when an older database still has them."""
    if not _table_exists(conn, TABLE):
        return
    if _index_exists(conn, RETIRED_INDEX, TABLE):
        escaped = RETIRED_INDEX.replace('"', '""')
        conn.execute(f'DROP INDEX IF EXISTS "{escaped}"')
    if _column_exists(conn, TABLE, RETIRED_COLUMN):
        conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{RETIRED_COLUMN}"')


def invariants(conn: Any) -> None:
    """Prove that the retired pair surface is absent wherever the table exists."""
    if not _table_exists(conn, TABLE):
        return
    assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
        f"{TABLE}.{RETIRED_COLUMN} must be absent after convergence"
    )
    assert not _index_exists(conn, RETIRED_INDEX, TABLE), (
        f"{RETIRED_INDEX} must be absent after convergence"
    )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRES_INVARIANTS",
    "RETIRED_COLUMN",
    "RETIRED_INDEX",
    "TABLE",
    "apply",
    "invariants",
]
