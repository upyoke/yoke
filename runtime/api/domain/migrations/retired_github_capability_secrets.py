"""Purge retired long-lived project GitHub credentials."""

from __future__ import annotations

from typing import Any

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.schema_common import _table_exists


TABLE = "capability_secrets"


def apply(conn: Any) -> None:
    """Delete only rows from the retired GitHub capability-secret surface."""

    _require_table(conn)
    conn.execute(f"LOCK TABLE {TABLE} IN EXCLUSIVE MODE")
    unrelated_before = _unrelated_count(conn)
    conn.execute(
        f"DELETE FROM {TABLE} WHERE LOWER(TRIM(type)) = %s",
        (GITHUB_CAPABILITY_TYPE,),
    )
    if _retired_count(conn):
        raise AssertionError("retired project GitHub credentials remain")
    unrelated_after = _unrelated_count(conn)
    if unrelated_after != unrelated_before:
        raise AssertionError(
            "unrelated capability-secret row count changed from "
            f"{unrelated_before} to {unrelated_after}"
        )


def invariants(conn: Any) -> None:
    """Verify the retired GitHub credential surface has no stored rows."""

    _require_table(conn)
    remaining = _retired_count(conn)
    if remaining:
        raise AssertionError(
            f"{remaining} retired project GitHub credential row(s) remain"
        )


def _require_table(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        raise AssertionError(f"{TABLE} table is required before this migration")


def _retired_count(conn: Any) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE LOWER(TRIM(type)) = %s",
        (GITHUB_CAPABILITY_TYPE,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _unrelated_count(conn: Any) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE LOWER(TRIM(type)) <> %s",
        (GITHUB_CAPABILITY_TYPE,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


__all__ = ["TABLE", "apply", "invariants"]
