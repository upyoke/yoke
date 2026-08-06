"""Portable fingerprints separate schema meaning from database ownership."""

from __future__ import annotations

import uuid

import psycopg
from psycopg import sql

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.schema_fingerprint import (
    fingerprint_kind,
    fingerprint_portable_postgres_schema,
)


def test_owner_handoff_does_not_move_fingerprints_but_body_drift_does(
    cluster_role_authority,
) -> None:
    role = f"fingerprint_owner_{uuid.uuid4().hex[:12]}"
    database = pg_testdb.create_test_database(pooled=False)
    dsn = pg_testdb.dsn_for_test_database(database)
    maintenance = pg_testdb.maintenance_dsn()
    try:
        with psycopg.connect(maintenance, autocommit=True) as authority:
            authority.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "CREATE TABLE portable_evidence (migration_name TEXT PRIMARY KEY)"
            )
            conn.execute(
                "CREATE FUNCTION portable_evidence_guard() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$"
            )
            conn.execute(
                "CREATE TRIGGER portable_evidence_guard BEFORE DELETE "
                "ON portable_evidence FOR EACH ROW "
                "EXECUTE FUNCTION portable_evidence_guard()"
            )
            conn.commit()
            exact_before = fingerprint_kind("postgres", conn)
            portable_before = fingerprint_portable_postgres_schema(conn)

            conn.execute(
                sql.SQL("GRANT {} TO CURRENT_USER").format(sql.Identifier(role))
            )
            conn.execute(
                sql.SQL("ALTER TABLE portable_evidence OWNER TO {}").format(
                    sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("ALTER FUNCTION portable_evidence_guard() OWNER TO {}").format(
                    sql.Identifier(role)
                )
            )
            conn.commit()

            assert fingerprint_kind("postgres", conn) == exact_before
            assert fingerprint_portable_postgres_schema(conn) == portable_before

            conn.execute(
                "CREATE OR REPLACE FUNCTION portable_evidence_guard() "
                "RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'changed'; END $$"
            )
            conn.commit()
            assert fingerprint_kind("postgres", conn) != exact_before
            assert fingerprint_portable_postgres_schema(conn) != portable_before
    finally:
        pg_testdb.drop_test_database(database, pooled=False)
        with psycopg.connect(maintenance, autocommit=True) as authority:
            authority.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
            )
