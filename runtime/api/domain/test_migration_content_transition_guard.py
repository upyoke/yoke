"""Legacy digest transitions require matching immutable evidence."""

from __future__ import annotations

import sqlite3

import psycopg
import pytest
from psycopg import sql

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.migration_audit_schema import ensure_migration_ledger_table
from yoke_core.domain.migration_content_schema import (
    AdoptionEvidenceContract,
    converge_migration_content_schema,
    migration_content_schema_is_prepared,
)
from yoke_core.domain.migration_content_transition_guard import (
    adoption_transition_guard_is_enforced,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract


LEDGER = LedgerContract(
    table="project_history",
    entry_column="entry_id",
    digest_column="body_hash",
    serving_floor_column="engine_floor",
)
EVIDENCE = AdoptionEvidenceContract(
    table="project_history_adoptions",
    entry_column="entry_id",
    content_digest_column="body_hash",
)
DIGEST = "a" * 64


def _prepare(conn) -> None:
    ensure_migration_ledger_table(conn, LEDGER, EVIDENCE)


def _insert_ledger(conn, digest: str | None) -> None:
    marker = "%s" if not isinstance(conn, sqlite3.Connection) else "?"
    conn.execute(
        f"INSERT INTO {LEDGER.table} "
        f"({LEDGER.entry_column}, {LEDGER.applied_at_column}, "
        f"{LEDGER.applied_by_column}, {LEDGER.serving_floor_column}, "
        f"{LEDGER.digest_column}) VALUES "
        f"({marker}, {marker}, {marker}, {marker}, {marker})",
        ("0001_existing", "now", "test", None, digest),
    )
    conn.commit()


def _insert_evidence(conn, digest: str) -> None:
    marker = "%s" if not isinstance(conn, sqlite3.Connection) else "?"
    conn.execute(
        f"INSERT INTO {EVIDENCE.table} VALUES "
        f"({', '.join(marker for _column in range(9))})",
        (
            "0001_existing",
            digest,
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


def test_sqlite_digest_born_with_membership_needs_no_adoption_evidence() -> None:
    conn = sqlite3.connect(":memory:")
    _prepare(conn)

    _insert_ledger(conn, DIGEST)

    assert conn.execute(
        f"SELECT {LEDGER.digest_column} FROM {LEDGER.table}"
    ).fetchone() == (DIGEST,)
    assert conn.execute(f"SELECT count(*) FROM {EVIDENCE.table}").fetchone() == (0,)


@pytest.mark.parametrize("evidence_digest", [None, "b" * 64])
def test_sqlite_direct_adoption_requires_matching_evidence(
    evidence_digest: str | None,
) -> None:
    conn = sqlite3.connect(":memory:")
    _prepare(conn)
    _insert_ledger(conn, None)
    if evidence_digest is not None:
        _insert_evidence(conn, evidence_digest)

    with pytest.raises(sqlite3.IntegrityError, match="matching immutable evidence"):
        conn.execute(
            f"UPDATE {LEDGER.table} SET {LEDGER.digest_column} = ?",
            (DIGEST,),
        )
    conn.rollback()

    assert conn.execute(
        f"SELECT {LEDGER.digest_column} FROM {LEDGER.table}"
    ).fetchone() == (None,)


def test_sqlite_convergence_repairs_semantically_wrong_transition_guard() -> None:
    conn = sqlite3.connect(":memory:")
    _prepare(conn)
    _insert_ledger(conn, None)
    name = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (LEDGER.table,),
    ).fetchone()[0]
    conn.execute(f"DROP TRIGGER {name}")
    conn.execute(
        f"CREATE TRIGGER {name} BEFORE UPDATE ON {LEDGER.table} "
        "BEGIN SELECT 1; END"
    )

    assert not migration_content_schema_is_prepared(conn, LEDGER, EVIDENCE)
    converge_migration_content_schema(conn, LEDGER, EVIDENCE)

    assert migration_content_schema_is_prepared(conn, LEDGER, EVIDENCE)
    with pytest.raises(sqlite3.IntegrityError, match="matching immutable evidence"):
        conn.execute(
            f"UPDATE {LEDGER.table} SET {LEDGER.digest_column} = ?",
            (DIGEST,),
        )


def test_postgres_direct_adoption_requires_matching_evidence() -> None:
    with pg_testdb.test_database() as conn:
        _prepare(conn)
        _insert_ledger(conn, None)
        _insert_evidence(conn, "b" * 64)

        with pytest.raises(psycopg.errors.RaiseException, match="matching immutable"):
            conn.execute(
                f"UPDATE {LEDGER.table} SET {LEDGER.digest_column} = %s",
                (DIGEST,),
            )
        conn.rollback()

        assert conn.execute(
            f"SELECT {LEDGER.digest_column} FROM {LEDGER.table}"
        ).fetchone() == (None,)


def test_postgres_convergence_reenables_transition_guard() -> None:
    with pg_testdb.test_database() as conn:
        _prepare(conn)
        trigger = conn.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(%s) "
            "AND NOT tgisinternal",
            (LEDGER.table,),
        ).fetchone()[0]
        conn.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier(LEDGER.table), sql.Identifier(trigger)
            )
        )

        assert not adoption_transition_guard_is_enforced(conn, LEDGER, EVIDENCE)
        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_transition_guard_is_enforced(conn, LEDGER, EVIDENCE)


def test_postgres_convergence_restores_transition_function_body() -> None:
    with pg_testdb.test_database() as conn:
        _prepare(conn)
        function = conn.execute(
            "SELECT procedure.proname FROM pg_trigger AS trigger "
            "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
            "WHERE trigger.tgrelid = to_regclass(%s) "
            "AND NOT trigger.tgisinternal",
            (LEDGER.table,),
        ).fetchone()[0]
        conn.execute(
            sql.SQL(
                "CREATE OR REPLACE FUNCTION {}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"
            ).format(sql.Identifier(function))
        )

        assert not adoption_transition_guard_is_enforced(conn, LEDGER, EVIDENCE)
        converge_migration_content_schema(conn, LEDGER, EVIDENCE)

        assert adoption_transition_guard_is_enforced(conn, LEDGER, EVIDENCE)
