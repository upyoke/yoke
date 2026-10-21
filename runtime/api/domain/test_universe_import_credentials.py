"""Imported credential rotation, recovery, and transaction isolation."""

import pytest

from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from yoke_core.domain import universe_import_credentials as credentials
from yoke_core.domain import universe_import_cli as importer
from yoke_core.domain.api_tokens import bootstrap_admin_token, hash_token


def test_credential_handoff_rolls_back_as_one_transaction():
    with _canonical_universe() as (conn, _dsn):
        original = bootstrap_admin_token(conn)
        replacement = None
        with pytest.raises(RuntimeError, match="force rollback"):
            with conn.transaction():
                replacement = credentials.replace_imported_credentials(conn)
                raise RuntimeError("force rollback")
        assert replacement is not None
        assert conn.execute(
            "SELECT status FROM api_tokens WHERE token_hash = %s",
            (hash_token(original.raw_token),),
        ).fetchone() == ("active",)
        assert (
            conn.execute(
                "SELECT 1 FROM api_tokens WHERE token_hash = %s",
                (hash_token(replacement.raw_token),),
            ).fetchone()
            is None
        )



def test_import_finalizer_requires_exactly_one_organization():
    with _canonical_universe() as (conn, _dsn):
        conn.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('second', 'Second', now())"
        )
        conn.commit()
        with pytest.raises(
            credentials.UniverseImportCredentialError, match="exactly one"
        ):
            credentials.replace_imported_credentials(conn)



def test_recovery_revokes_every_prior_import_recovery_token():
    with _canonical_universe() as (conn, dsn):
        original = bootstrap_admin_token(conn)
        imported = credentials.replace_imported_credentials(conn)
        conn.commit()
        recovered = importer.recover_credential(dsn=dsn)
        recovered_again = importer.recover_credential(dsn=dsn)

        rows = conn.execute(
            "SELECT token_hash, status FROM api_tokens ORDER BY id"
        ).fetchall()
        by_hash = {str(row[0]): str(row[1]) for row in rows}
        assert by_hash[hash_token(original.raw_token)] == "revoked"
        assert by_hash[hash_token(imported.raw_token)] == "revoked"
        assert by_hash[hash_token(str(recovered["raw_token"]))] == "revoked"
        assert by_hash[hash_token(str(recovered_again["raw_token"]))] == "active"
        assert recovered["revoked_token_count"] == 1
        assert recovered_again["revoked_token_count"] == 1



@pytest.mark.parametrize("slug", ("unsafe\nsummary", "a" * 129))
def test_credential_handoff_rejects_unsafe_org_slug_before_rotation(slug):
    with _canonical_universe() as (conn, _dsn):
        original = bootstrap_admin_token(conn)
        conn.execute("UPDATE organizations SET slug = %s", (slug,))
        conn.commit()
        with pytest.raises(
            credentials.UniverseImportCredentialError,
            match="bounded safe identifier",
        ):
            credentials.replace_imported_credentials(conn)
        conn.rollback()
        assert conn.execute(
            "SELECT status FROM api_tokens WHERE token_hash = %s",
            (hash_token(original.raw_token),),
        ).fetchone() == ("active",)

