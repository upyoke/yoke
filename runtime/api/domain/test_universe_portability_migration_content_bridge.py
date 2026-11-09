"""Migration-content metadata stays portable across its additive rollout."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.domain.universe_portability_test_support import (
    _canonical_test_universe,
)
from runtime.api.fixtures import pg_testdb
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.source_authority_receipts import authority_receipt


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
                match="catalog|columns",
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
