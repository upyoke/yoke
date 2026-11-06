"""Restored owner admission preserves archived people and refuses live authority."""

import pytest
from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from yoke_core.domain.universe_import_admission import admit_restored_owner
from yoke_core.domain.api_tokens import bootstrap_admin_token
from yoke_core.domain.universe_import_credentials import revoke_imported_credentials
from yoke_core.domain.actors import seed_human_actor
from runtime.api.fixtures.actor_roles import seed_org_role


def admit(conn):
    return admit_restored_owner(conn, issuer="https://accounts.google.com", subject="verified-importer",
                                email="importer@example.test", name="Importer")


def test_restored_owner_preserves_existing_owners_and_caller_transaction():
    with _canonical_universe() as (conn, _dsn):
        first = bootstrap_admin_token(conn).actor_id
        other = seed_human_actor(conn, "Another owner")
        org = conn.execute("SELECT id FROM organizations").fetchone()[0]
        seed_org_role(conn, actor_id=other, org_id=org, role_name="owner")
        revoke_imported_credentials(conn)
        before = conn.execute("SELECT actor_id FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id WHERE r.name='owner' ORDER BY actor_id").fetchall()
        importer = admit(conn)
        assert importer not in (first, other)
        assert conn.execute("SELECT actor_id FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id WHERE r.name='owner' ORDER BY actor_id").fetchall() == [*before, (importer,)]
        conn.rollback()
        assert conn.execute("SELECT 1 FROM actors WHERE id=%s", (importer,)).fetchone() is None


def test_live_human_credentials_refuse_before_identity_creation():
    with _canonical_universe() as (conn, _dsn):
        bootstrap_admin_token(conn)
        before = conn.execute("SELECT count(*) FROM actors").fetchone()[0]
        with pytest.raises(ValueError, match="retired human credentials"):
            admit(conn)
        assert conn.execute("SELECT count(*) FROM actors").fetchone()[0] == before
