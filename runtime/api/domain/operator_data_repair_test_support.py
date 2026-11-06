# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import hashlib

import json

import pytest

from runtime.api.fixtures.pg_testdb import test_database as isolated_database

from yoke_core.domain import operator_data_repair as repair

from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table

from yoke_core.domain.operator_data_repair_sql import RepairRefusal


@pytest.fixture
def conn():
    with isolated_database() as connection:
        ensure_migration_audit_table(connection)
        connection.execute(
            "CREATE TABLE repair_documents (id integer PRIMARY KEY, document text NOT NULL)"
        )
        connection.execute(
            "INSERT INTO repair_documents VALUES (1, 'old'), (2, 'unrelated')"
        )
        connection.commit()
        yield connection


def execute(conn, document, *, dry_run=False):
    return repair.run_repair(
        conn,
        document,
        reviewed_sha256=repair.review_digest(document),
        actor_id=2,
        project_id=1,
        dry_run=dry_run,
    )


def receipt(conn):
    return conn.execute(
        "SELECT state, source_fingerprint, baseline_verify_result, author_verify_result, failure_reason, actor_id FROM public.migration_audit WHERE migration_name='operator_data_repair' ORDER BY id DESC LIMIT 1"
    ).fetchone()
