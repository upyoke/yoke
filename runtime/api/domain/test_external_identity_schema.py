"""Schema-init coverage for the external sign-in identity tables."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import (
    REQUIRED_EXTERNAL_IDENTITY_TABLES,
    create_external_identity_tables,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        seed_roles_and_permissions(c)
        seed_default_org(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_fresh_create_then_rerun_is_idempotent(conn):
    create_external_identity_tables(conn)
    for table in REQUIRED_EXTERNAL_IDENTITY_TABLES:
        assert _table_exists(conn, table), f"missing table {table}"
    assert _column_exists(conn, "organizations", "auto_join_domain")

    # Re-run against the already-initialized DB: no error, same shape.
    create_external_identity_tables(conn)
    for table in REQUIRED_EXTERNAL_IDENTITY_TABLES:
        assert _table_exists(conn, table)
    assert _column_exists(conn, "organizations", "auto_join_domain")


def test_external_identity_unique_on_issuer_subject(conn):
    create_external_identity_tables(conn)
    actor_id = seed_human_actor(conn)
    conn.execute(
        "INSERT INTO actor_external_identities "
        "(actor_id, issuer, subject, linked_at) "
        "VALUES (%s, 'https://issuer.example', 'sub-1', '2026-01-01T00:00:00Z')",
        (actor_id,),
    )
    conn.commit()
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO actor_external_identities "
            "(actor_id, issuer, subject, linked_at) "
            "VALUES (%s, 'https://issuer.example', 'sub-1', '2026-01-01T00:00:00Z')",
            (actor_id,),
        )
    conn.rollback()


def test_pending_invite_unique_is_case_insensitive_and_scoped_to_pending(conn):
    create_external_identity_tables(conn)
    actor_id = seed_human_actor(conn)
    org_row = conn.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()
    org_id = int(org_row[0])
    conn.execute(
        "INSERT INTO actor_invites (email, org_id, invited_by_actor_id, created_at) "
        "VALUES ('Person@Example.com', %s, %s, '2026-01-01T00:00:00Z')",
        (org_id, actor_id),
    )
    conn.commit()
    # A second pending invite for the same case-folded email collides.
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO actor_invites (email, org_id, invited_by_actor_id, created_at) "
            "VALUES ('person@example.com', %s, %s, '2026-01-01T00:00:00Z')",
            (org_id, actor_id),
        )
    conn.rollback()
    # A non-pending row does not participate in the partial unique index.
    conn.execute(
        "UPDATE actor_invites SET status = 'revoked' WHERE email = 'Person@Example.com'"
    )
    conn.execute(
        "INSERT INTO actor_invites (email, org_id, invited_by_actor_id, created_at) "
        "VALUES ('person@example.com', %s, %s, '2026-01-02T00:00:00Z')",
        (org_id, actor_id),
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM actor_invites").fetchone()[0]
    assert int(count) == 2
