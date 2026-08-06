"""Migration-content metadata stays portable across its additive rollout."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.domain.test_universe_portability import _canonical_test_universe
from runtime.api.fixtures import pg_testdb
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)
from yoke_core.domain.source_authority_receipts import authority_receipt


CONTENT_MIGRATION = "0006_migration_content_identity"


def _remove_content_identity_schema(conn: psycopg.Connection) -> tuple[str, ...]:
    """Make a current fixture represent an authentic pre-content archive."""
    conn.execute("ALTER TABLE applied_migrations DISABLE TRIGGER USER")
    conn.execute(
        "DELETE FROM applied_migrations WHERE migration_name >= %s",
        (CONTENT_MIGRATION,),
    )
    conn.execute(
        "DELETE FROM migration_audit WHERE migration_name >= %s",
        (CONTENT_MIGRATION,),
    )
    names = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT migration_name FROM applied_migrations ORDER BY migration_name"
        ).fetchall()
    )
    assert names
    conn.execute("DROP TABLE migration_content_adoptions CASCADE")
    conn.execute("ALTER TABLE applied_migrations DROP COLUMN content_sha256 CASCADE")
    conn.commit()
    return names


def test_pre_content_archive_restores_and_converges_to_current_schema(tmp_path) -> None:
    with _canonical_test_universe() as (source, source_dsn):
        with _canonical_test_universe() as (reference, _reference_dsn):
            expected_fingerprint = fingerprint_portable_postgres_schema(reference)
        source.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
            "VALUES (88901, 'portable-content', 'Portable Content', 'PCM', now())"
        )
        legacy_names = _remove_content_identity_schema(source)
        archive = tmp_path / "pre-content-identity.dump"
        portability.dump_universe(source_dsn, archive)

        target_database = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_database)
        try:
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as restored:
                rows = restored.execute(
                    "SELECT migration_name, content_sha256 "
                    "FROM applied_migrations ORDER BY migration_name"
                ).fetchall()
                assert tuple(str(row[0]) for row in rows) == legacy_names
                assert all(row[1] is None for row in rows)
                assert restored.execute(
                    "SELECT COUNT(*) FROM migration_content_adoptions"
                ).fetchone() == (0,)

            result = portability.converge_and_validate_restored_universe(
                target_dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fingerprint,
            )
            assert result["org"] == "default"
            with psycopg.connect(target_dsn) as converged:
                assert converged.execute(
                    "SELECT name FROM projects WHERE id=88901"
                ).fetchone() == ("Portable Content",)
                rows = converged.execute(
                    "SELECT migration_name, content_sha256 "
                    "FROM applied_migrations ORDER BY migration_name"
                ).fetchall()
                digest_by_name = {str(row[0]): row[1] for row in rows}
                assert all(digest_by_name[name] is None for name in legacy_names)
                assert len(str(digest_by_name[CONTENT_MIGRATION])) == 64
        finally:
            pg_testdb.drop_test_database(target_database)


@pytest.mark.parametrize(
    "drop_statement",
    (
        "DROP TABLE migration_content_adoptions CASCADE",
        "ALTER TABLE applied_migrations DROP COLUMN content_sha256 CASCADE",
    ),
    ids=("missing-evidence-table", "missing-ledger-digest"),
)
def test_partial_content_identity_archive_shape_is_rejected(
    tmp_path, drop_statement: str
) -> None:
    with _canonical_test_universe() as (source, source_dsn):
        source.execute(drop_statement)
        source.commit()
        archive = tmp_path / "partial-content-identity.dump"
        portability.dump_universe(source_dsn, archive)

        target_database = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_database)
        try:
            with pytest.raises(
                portability.ArchiveCompatibilityError,
                match="must be present or absent together",
            ):
                portability.restore_universe(archive, target_dsn)
        finally:
            pg_testdb.drop_test_database(target_database)


def test_adoption_evidence_rows_travel_in_portable_content_receipts(tmp_path) -> None:
    with _canonical_test_universe() as (source, source_dsn):
        source.execute(
            "INSERT INTO migration_content_adoptions ("
            "migration_name, content_sha256, artifact_engine_version, "
            "source_artifact, source_sha256, source_commit, manifest_sha256, "
            "adopted_by, adopted_at) VALUES "
            "('legacy_portable_proof', %s, 'test-engine', 'test-artifact', %s, "
            "%s, %s, 'test-operator', '2026-08-06T00:00:00Z')",
            ("a" * 64, "b" * 64, "c" * 40, "d" * 64),
        )
        source.commit()
        source_receipt = authority_receipt(source, include_content_digests=True)
        evidence_receipt = source_receipt["tables"]["migration_content_adoptions"]
        assert evidence_receipt["count"] == 1
        assert len(evidence_receipt["digest"]) == 64

        archive = tmp_path / "content-evidence.dump"
        portability.dump_universe(source_dsn, archive)
        target_database = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_database)
        try:
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as restored:
                assert restored.execute(
                    "SELECT content_sha256, source_commit "
                    "FROM migration_content_adoptions "
                    "WHERE migration_name='legacy_portable_proof'"
                ).fetchone() == ("a" * 64, "c" * 40)
                restored_receipt = authority_receipt(
                    restored, include_content_digests=True
                )
                assert restored_receipt["tables"]["migration_content_adoptions"] == (
                    evidence_receipt
                )
                assert (
                    restored_receipt["receipt_digest"]
                    == (source_receipt["receipt_digest"])
                )
        finally:
            pg_testdb.drop_test_database(target_database)
