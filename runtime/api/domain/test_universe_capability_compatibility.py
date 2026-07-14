"""Typed capability compatibility at portable-universe cutover."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest

from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)


@contextmanager
def _canonical_test_universe():
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)


def test_restored_universe_refuses_incompatible_typed_capability_settings():
    with _canonical_test_universe() as (conn, dsn):
        expected = fingerprint_portable_postgres_schema(conn)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) VALUES "
            "(1, 'yoke', 'Yoke', 'YOK', now())"
        )
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES "
            "(1, 'github-actions-runner-fleet', "
            "'{\"unexpected_field\": \"old\"}', now())"
        )
        conn.commit()

        with pytest.raises(
            portability.ArchiveCompatibilityError,
            match="project 'yoke' capability 'github-actions-runner-fleet'",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected,
            )
