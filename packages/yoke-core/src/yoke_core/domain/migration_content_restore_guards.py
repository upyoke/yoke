"""Sanctioned full-replacement handling for adoption-evidence guards."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Tuple

from psycopg import sql

from yoke_core.domain.migration_content_schema import (
    ADOPTION_EVIDENCE_GUARD_PREFIX,
)


GuardTarget = Tuple[str, str, str]


def _truncate_guard_targets(conn: Any) -> Tuple[GuardTarget, ...]:
    rows = conn.execute(
        "SELECT namespace.nspname::text, relation.relname::text, "
        "trigger.tgname::text "
        "FROM pg_catalog.pg_trigger AS trigger "
        "JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid "
        "JOIN pg_catalog.pg_namespace AS namespace "
        "ON namespace.oid = relation.relnamespace "
        "JOIN pg_catalog.pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
        "WHERE namespace.nspname = current_schema() "
        "AND NOT trigger.tgisinternal "
        "AND strpos(procedure.proname, %s) = 1 "
        "AND right(trigger.tgname, 9) = '_truncate' "
        "ORDER BY relation.relname, trigger.tgname",
        (ADOPTION_EVIDENCE_GUARD_PREFIX,),
    ).fetchall()
    return tuple((str(row[0]), str(row[1]), str(row[2])) for row in rows)


def _set_guard_enabled(conn: Any, target: GuardTarget, *, enabled: bool) -> None:
    namespace, table, trigger = target
    state = sql.SQL("ENABLE") if enabled else sql.SQL("DISABLE")
    conn.execute(
        sql.SQL("ALTER TABLE {}.{} {} TRIGGER {}").format(
            sql.Identifier(namespace),
            sql.Identifier(table),
            state,
            sql.Identifier(trigger),
        )
    )


@contextmanager
def suspended_adoption_evidence_truncate_guards(
    conn: Any,
) -> Iterator[Tuple[GuardTarget, ...]]:
    """Disable only owned TRUNCATE guards inside the caller's transaction.

    Full-universe replacement clears trusted bootstrap rows before restoring
    archive data. UPDATE/DELETE guards remain active throughout; TRUNCATE
    guards are re-enabled before this context returns or propagates failure.
    PostgreSQL rolls every trigger-state change back with the transaction.
    """
    targets = _truncate_guard_targets(conn)
    disabled: list[GuardTarget] = []
    try:
        for target in targets:
            _set_guard_enabled(conn, target, enabled=False)
            disabled.append(target)
        yield targets
    finally:
        for target in reversed(disabled):
            _set_guard_enabled(conn, target, enabled=True)


def truncate_trusted_schema_bootstrap_rows(conn: Any) -> None:
    """Clear every trusted-schema table while preserving evidence guards."""
    tables = conn.execute(
        "SELECT tablename::text FROM pg_catalog.pg_tables "
        "WHERE schemaname = current_schema() ORDER BY tablename"
    ).fetchall()
    if not tables:
        return
    identifiers = [sql.Identifier(str(row[0])) for row in tables]
    with suspended_adoption_evidence_truncate_guards(conn):
        conn.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(identifiers)
            )
        )


__all__ = [
    "suspended_adoption_evidence_truncate_guards",
    "truncate_trusted_schema_bootstrap_rows",
]
