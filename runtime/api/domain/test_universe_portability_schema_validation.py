"""Portable restore convergence and schema compatibility checks."""

from runtime.api.domain.universe_portability_schema_validation_test_support import (
    assert_older_schema_restored as assert_older_schema_restored,
    seed_older_schema as seed_older_schema,
)


import os
import pytest
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)


def test_schema_fingerprint_and_org_identity_fail_closed(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        dsn = os.environ[db_backend.PG_DSN_ENV]
        expected = fingerprint_portable_postgres_schema(conn)
        # Finish catalog reads before another connection converges source tables.
        conn.commit()
        with pytest.raises(
            portability.ArchiveCompatibilityError,
            match="does not match",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="different-org",
                expected_schema_fingerprint=expected,
            )
        conn.execute("CREATE TABLE future_only_table (id bigint PRIMARY KEY)")
        conn.commit()
        with pytest.raises(
            portability.ArchiveCompatibilityError,
            match="not compatible",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected,
            )
