"""Add raw-byte content identity to the permanent migration ledger.

Existing membership rows intentionally remain NULL.  Their historical bytes
cannot be reconstructed safely from today's checkout, so adoption is an
explicit artifact-manifest operation with its own evidence row.  New applies
and newborn stamps record their digest as part of the membership transaction.
"""

from __future__ import annotations


def apply(conn) -> None:
    from yoke_core.domain.migration_yoke_ledger import (
        converge_yoke_migration_content_schema,
    )

    converge_yoke_migration_content_schema(conn)


def invariants(conn) -> None:
    from yoke_core.domain.migration_yoke_ledger import (
        YOKE_ADOPTION_EVIDENCE_TABLE,
        YOKE_DIGEST_COLUMN,
        YOKE_LEDGER_TABLE,
    )
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _column_exists(conn, YOKE_LEDGER_TABLE, YOKE_DIGEST_COLUMN):
        raise AssertionError(f"{YOKE_LEDGER_TABLE}.{YOKE_DIGEST_COLUMN} is missing")
    if not _table_exists(conn, YOKE_ADOPTION_EVIDENCE_TABLE):
        raise AssertionError(f"{YOKE_ADOPTION_EVIDENCE_TABLE} is missing")
    for column in ("source_commit", "manifest_sha256"):
        if not _column_exists(conn, YOKE_ADOPTION_EVIDENCE_TABLE, column):
            raise AssertionError(f"{YOKE_ADOPTION_EVIDENCE_TABLE}.{column} is missing")


__all__ = ["apply", "invariants"]
