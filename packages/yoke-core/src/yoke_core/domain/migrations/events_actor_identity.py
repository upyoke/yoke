"""Make actor identity the only human identity on the event ledger."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
    _get_indexes,
    _table_exists,
)


EVENTS_TABLE = "events"
RETIRED_COLUMN = "user_id"
RETIRED_INDEX = "idx_events_user_id"
_JSONB_SAFE_ENVELOPE = (
    "REPLACE(envelope, CHR(92) || 'u0000', CHR(92) || 'u0001')::jsonb"
)


def apply(conn: Any) -> None:
    """Drop the unused human-user column without changing ledger rows."""

    if not _table_exists(conn, EVENTS_TABLE):
        raise AssertionError(f"{EVENTS_TABLE} table is required before this migration")

    conn.execute(f"LOCK TABLE {EVENTS_TABLE} IN ACCESS EXCLUSIVE MODE")
    before = _row_count(conn)
    column_exists = _column_exists(conn, EVENTS_TABLE, RETIRED_COLUMN)
    index_exists = RETIRED_INDEX in set(_get_indexes(conn, EVENTS_TABLE))
    envelope_identities = _nonnull_envelope_identity_count(conn)
    if envelope_identities:
        raise AssertionError(
            f"{EVENTS_TABLE}.envelope has {envelope_identities} non-null "
            f"{RETIRED_COLUMN} values; refusing to preserve human identity data"
        )

    if not column_exists:
        if index_exists:
            raise AssertionError(
                f"{RETIRED_INDEX} exists without {EVENTS_TABLE}.{RETIRED_COLUMN}"
            )
        _assert_row_count(conn, before)
        return

    if not index_exists:
        raise AssertionError(
            f"{EVENTS_TABLE}.{RETIRED_COLUMN} exists without {RETIRED_INDEX}; "
            "refusing an unrecognized pre-migration shape"
        )

    populated = _nonempty_value_count(conn)
    if populated:
        raise AssertionError(
            f"{EVENTS_TABLE}.{RETIRED_COLUMN} has {populated} non-empty values; "
            "refusing to discard human identity data"
        )
    conn.execute(f"DROP INDEX {RETIRED_INDEX}")
    conn.execute(f"ALTER TABLE {EVENTS_TABLE} DROP COLUMN {RETIRED_COLUMN}")
    _assert_row_count(conn, before)


def invariants(conn: Any) -> None:
    """Verify row preservation and complete removal of the old surface."""

    if not _table_exists(conn, EVENTS_TABLE):
        raise AssertionError(f"{EVENTS_TABLE} table is missing")
    if _column_exists(conn, EVENTS_TABLE, RETIRED_COLUMN):
        raise AssertionError(f"{EVENTS_TABLE}.{RETIRED_COLUMN} is still present")
    if RETIRED_INDEX in set(_get_indexes(conn, EVENTS_TABLE)):
        raise AssertionError(f"{RETIRED_INDEX} is still present")
    if _nonnull_envelope_identity_count(conn):
        raise AssertionError(
            f"{EVENTS_TABLE}.envelope contains non-null {RETIRED_COLUMN} values"
        )


def _row_count(conn: Any) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {EVENTS_TABLE}").fetchone()
    return int(row[0]) if row is not None else 0


def _nonempty_value_count(conn: Any) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {EVENTS_TABLE} "
        f"WHERE TRIM(COALESCE({RETIRED_COLUMN}, '')) <> ''"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _nonnull_envelope_identity_count(conn: Any) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {EVENTS_TABLE} "
        f"WHERE jsonb_typeof({_JSONB_SAFE_ENVELOPE}) = 'object' "
        f"AND {_JSONB_SAFE_ENVELOPE} ? '{RETIRED_COLUMN}' "
        f"AND {_JSONB_SAFE_ENVELOPE} -> '{RETIRED_COLUMN}' "
        "IS DISTINCT FROM 'null'::jsonb"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _assert_row_count(conn: Any, expected: int) -> None:
    actual = _row_count(conn)
    if actual != expected:
        raise AssertionError(
            f"{EVENTS_TABLE} row count changed from {expected} to {actual}"
        )


__all__ = [
    "EVENTS_TABLE",
    "RETIRED_COLUMN",
    "RETIRED_INDEX",
    "apply",
    "invariants",
]
