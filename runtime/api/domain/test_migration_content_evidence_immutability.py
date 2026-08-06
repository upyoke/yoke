"""Database enforcement for append-only migration adoption evidence."""

from __future__ import annotations

import sqlite3

import psycopg
import pytest
from psycopg import sql

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.migration_audit_schema import ensure_migration_ledger_table
from yoke_core.domain.migration_content_schema import (
    AdoptionEvidenceContract,
    adoption_evidence_is_immutable,
    converge_migration_content_schema,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_content_restore_guards import (
    truncate_trusted_schema_bootstrap_rows,
)


LEDGER = LedgerContract(
    table="immutable_history",
    entry_column="entry_id",
    digest_column="body_hash",
    serving_floor_column="engine_floor",
)
EVIDENCE = AdoptionEvidenceContract(table="immutable_history_adoptions")


def _seed(conn) -> None:
    ensure_migration_ledger_table(conn, LEDGER, EVIDENCE)
    marker = "%s" if not isinstance(conn, sqlite3.Connection) else "?"
    conn.execute(
        f"INSERT INTO {EVIDENCE.table} VALUES "
        f"({', '.join(marker for _column in range(9))})",
        (
            "0001_existing",
            "a" * 64,
            "1.2.3",
            "engine.whl",
            "b" * 64,
            "c" * 40,
            "d" * 64,
            "operator:test",
            "2026-08-06T00:00:00Z",
        ),
    )
    conn.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE immutable_history_adoptions SET adopted_by='other'",
        "DELETE FROM immutable_history_adoptions",
    ],
)
def test_sqlite_evidence_refuses_update_and_delete(statement: str) -> None:
    conn = sqlite3.connect(":memory:")
    _seed(conn)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(statement)


def test_sqlite_convergence_restores_dropped_guards() -> None:
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (EVIDENCE.table,),
    ).fetchall()
    for row in rows:
        conn.execute(f"DROP TRIGGER {row[0]}")
    assert not adoption_evidence_is_immutable(conn, EVIDENCE)

    converge_migration_content_schema(conn, LEDGER, EVIDENCE)

    assert adoption_evidence_is_immutable(conn, EVIDENCE)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"DELETE FROM {EVIDENCE.table}")


@pytest.mark.parametrize("wrong_event", [True, False])
def test_sqlite_convergence_replaces_wrong_guard_semantics(wrong_event: bool) -> None:
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    names = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name=? ORDER BY name",
            (EVIDENCE.table,),
        ).fetchall()
    ]
    for name in names:
        conn.execute(f"DROP TRIGGER {name}")
    event = "INSERT" if wrong_event else "UPDATE"
    for name in names:
        conn.execute(
            f"CREATE TRIGGER {name} BEFORE {event} ON {EVIDENCE.table} "
            "BEGIN SELECT 1; END"
        )
    assert not adoption_evidence_is_immutable(conn, EVIDENCE)

    converge_migration_content_schema(conn, LEDGER, EVIDENCE)

    assert adoption_evidence_is_immutable(conn, EVIDENCE)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE immutable_history_adoptions SET adopted_by='other'",
        "DELETE FROM immutable_history_adoptions",
    ],
)
def test_postgres_evidence_refuses_update_and_delete(statement: str) -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(statement)
        conn.rollback()


def test_postgres_convergence_restores_dropped_guard_function() -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)
        row = conn.execute(
            "SELECT procedure.proname FROM pg_trigger AS trigger "
            "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
            "WHERE trigger.tgrelid = to_regclass(%s) "
            "AND NOT trigger.tgisinternal LIMIT 1",
            (EVIDENCE.table,),
        ).fetchone()
        assert row is not None
        conn.execute(
            sql.SQL("DROP FUNCTION {}() CASCADE").format(sql.Identifier(row[0]))
        )
        assert not adoption_evidence_is_immutable(conn, EVIDENCE)

        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_evidence_is_immutable(conn, EVIDENCE)
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(f"DELETE FROM {EVIDENCE.table}")


def _postgres_guard_objects(conn):
    return conn.execute(
        "SELECT trigger.tgname, procedure.proname FROM pg_trigger AS trigger "
        "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
        "WHERE trigger.tgrelid = to_regclass(%s) "
        "AND NOT trigger.tgisinternal ORDER BY trigger.tgname",
        (EVIDENCE.table,),
    ).fetchall()


def test_postgres_convergence_reenables_disabled_guard() -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)
        trigger = str(_postgres_guard_objects(conn)[0][0])
        conn.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier(EVIDENCE.table), sql.Identifier(trigger)
            )
        )
        assert not adoption_evidence_is_immutable(conn, EVIDENCE)

        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_evidence_is_immutable(conn, EVIDENCE)


def test_postgres_convergence_replaces_wrong_event_guard() -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)
        row_guard, function = _postgres_guard_objects(conn)[0]
        conn.execute(
            sql.SQL("DROP TRIGGER {} ON {}").format(
                sql.Identifier(row_guard), sql.Identifier(EVIDENCE.table)
            )
        )
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE UPDATE ON {} "
                "FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(
                sql.Identifier(row_guard),
                sql.Identifier(EVIDENCE.table),
                sql.Identifier(function),
            )
        )
        assert not adoption_evidence_is_immutable(conn, EVIDENCE)

        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_evidence_is_immutable(conn, EVIDENCE)


def test_postgres_convergence_replaces_wrong_guard_function_body() -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)
        function = str(_postgres_guard_objects(conn)[0][1])
        conn.execute(
            sql.SQL(
                "CREATE OR REPLACE FUNCTION {}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END; $$"
            ).format(sql.Identifier(function))
        )
        assert not adoption_evidence_is_immutable(conn, EVIDENCE)

        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_evidence_is_immutable(conn, EVIDENCE)


def test_full_replacement_truncate_preserves_append_only_guards() -> None:
    with pg_testdb.test_database() as conn:
        _seed(conn)

        truncate_trusted_schema_bootstrap_rows(conn)
        conn.commit()

        assert adoption_evidence_is_immutable(conn, EVIDENCE)
        _seed(conn)
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(f"TRUNCATE TABLE {EVIDENCE.table}")
        conn.rollback()
