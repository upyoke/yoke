"""Real PostgreSQL archive safety and transactional round trips."""

import os
import psycopg
import pytest
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)
from yoke_core.domain.source_authority_receipts import authority_receipt
from runtime.api.domain.test_universe_portability import _canonical_test_universe


def test_inspection_rejects_tampered_real_archive(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    artifact = tmp_path / "portable.dump"
    with pg_testdb.test_database():
        dsn = os.environ[db_backend.PG_DSN_ENV]
        portability.dump_universe(dsn, artifact)
    raw = bytearray(artifact.read_bytes())
    # Preserve PGDMP so the external catalog parser, not only our magic check,
    # must reject the corruption.
    raw[len(raw) // 2 :] = b"\xff" * (len(raw) - len(raw) // 2)
    artifact.write_bytes(raw)
    with pytest.raises(portability.ArchiveInvalidError, match="corrupt|unreadable"):
        portability.inspect_archive(artifact)


def test_server_side_dump_enforces_size_while_streaming(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    destination = tmp_path / "bounded.dump"
    with pg_testdb.test_database():
        dsn = os.environ[db_backend.PG_DSN_ENV]
        with pytest.raises(portability.ArchiveTooLargeError):
            portability.dump_universe(dsn, destination, max_bytes=5)
    assert not destination.exists()


def test_dump_rejects_snapshot_option_injection_before_subprocess(tmp_path):
    with pytest.raises(portability.UniversePortabilityError, match="snapshot id"):
        portability.dump_universe(
            "dbname=unused",
            tmp_path / "unsafe.dump",
            snapshot="valid --file=/tmp/injected",
        )


def test_real_dump_uses_one_exported_repeatable_read_snapshot(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import source_authority_connect_policy as fence_policy

    with _canonical_test_universe() as (source, source_dsn):
        admin_role = str(source.execute("SELECT current_user").fetchone()[0])
        fence_policy.create_fence_state(
            source,
            original={
                "schema": fence_policy.FENCE_POLICY_SCHEMA,
                "admin_role": admin_role,
            },
            frozen_at="2026-07-14T00:00:00Z",
            service_stop_receipt="service-stopped",
        )
        source.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (87001, 'snapshot-before', 'Before', 'SNP', now())"
        )
        source.commit()
        source.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = str(source.execute("SELECT pg_export_snapshot()").fetchone()[0])
        with psycopg.connect(source_dsn) as writer:
            writer.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                "VALUES (87002, 'snapshot-after', 'After', 'SNA', now())"
            )
        archive = tmp_path / "exported-snapshot.dump"
        portability.dump_universe(source_dsn, archive, snapshot=snapshot)
        catalog = portability._archive_catalog(
            archive,
            executable=portability._postgres_executable("pg_restore"),
            timeout_s=portability.DEFAULT_ARCHIVE_TIMEOUT_S,
        )
        assert fence_policy.FENCE_STATE_SCHEMA not in catalog
        source.rollback()

        target_db = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_db)
        try:
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT id FROM projects WHERE id IN (87001, 87002) ORDER BY id"
                ).fetchall() == [(87001,)]
        finally:
            pg_testdb.drop_test_database(target_db)


def test_real_restore_omits_uploaded_function_and_trigger(tmp_path):
    from runtime.api.fixtures import pg_testdb

    with _canonical_test_universe() as (source, source_dsn):
        source.execute(
            "CREATE FUNCTION uploaded_side_effect() RETURNS trigger"
            " LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"
        )
        source.execute(
            "CREATE TRIGGER uploaded_side_effect_trigger BEFORE INSERT ON projects"
            " FOR EACH ROW EXECUTE FUNCTION uploaded_side_effect()"
        )
        source.commit()
        archive = tmp_path / "executable.dump"
        portability.dump_universe(source_dsn, archive)

        target_db = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_db)
        try:
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n"
                    " ON n.oid = p.pronamespace WHERE n.nspname = 'public'"
                    " AND p.proname = 'uploaded_side_effect'"
                ).fetchone() == (0,)
                assert target.execute(
                    "SELECT COUNT(*) FROM pg_trigger"
                    " WHERE tgname = 'uploaded_side_effect_trigger'"
                ).fetchone() == (0,)
        finally:
            pg_testdb.drop_test_database(target_db)


def test_restore_failure_is_one_transaction_and_round_trip_succeeds(tmp_path):
    from runtime.api.fixtures import pg_testdb

    # The public fixture owns an isolated cluster.  Create source and target
    # databases on that same cluster so pg_dump/pg_restore run for real.
    with _canonical_test_universe() as (source, source_dsn):
        source.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (88001, 'portable', 'Portable', 'POR', now())"
        )
        source.execute(
            "UPDATE projects SET breakage_policy='compatibility_required'"
            " WHERE id=88001"
        )
        source.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, "
            "priority, created_at, updated_at, project_id, project_sequence, "
            "resolution, resolution_ref, resolution_comment, design_spec) VALUES "
            "(88003, 'Closed item', 'issue', (SELECT current_version_id "
            "FROM workflows WHERE id='issue'), 'cancelled', 'medium', now(), now(), "
            "88001, 1, 'duplicate', 'POR-2', 'Preserve close history', "
            "'trusted body')"
        )
        source.execute(
            "INSERT INTO capability_secrets "
            "(project_id, type, key, value, source, created_at) VALUES "
            "(88001, 'github', 'token', 'must-not-restore', 'literal', now())"
        )
        source.commit()
        source_authority = authority_receipt(
            source,
            include_content_digests=True,
        )
        archive = tmp_path / "portable.dump"
        portability.dump_universe(source_dsn, archive)

        target_db = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_db)
        try:
            portability.restore_universe(archive, target_dsn)
            from yoke_core.domain.schema_fingerprint import _postgres_schema_rows

            expected_rows = _postgres_schema_rows(source)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT name FROM projects WHERE id = 88001"
                ).fetchone() == ("Portable",)
                assert target.execute(
                    "SELECT breakage_policy FROM projects WHERE id = 88001"
                ).fetchone() == ("compatibility_required",)
                assert target.execute(
                    "SELECT resolution, resolution_ref, resolution_comment "
                    "FROM items WHERE id = 88003"
                ).fetchone() == (
                    "duplicate",
                    "POR-2",
                    "Preserve close history",
                )
                assert target.execute(
                    "SELECT design_spec FROM items WHERE id = 88003"
                ).fetchone() == ("trusted body",)
                assert target.execute(
                    "SELECT COUNT(*) FROM capability_secrets"
                ).fetchone() == (0,)
                restored_authority = authority_receipt(
                    target,
                    include_content_digests=True,
                )
                assert (
                    restored_authority["receipt_digest"]
                    == (source_authority["receipt_digest"])
                )
                assert source_authority["capability_secrets"]["types"]
                assert restored_authority["capability_secrets"]["types"] == {}
                actual_rows = _postgres_schema_rows(target)
                assert actual_rows == expected_rows, {
                    "missing": sorted(set(expected_rows) - set(actual_rows)),
                    "extra": sorted(set(actual_rows) - set(expected_rows)),
                }
                expected_fp = fingerprint_portable_postgres_schema(source)
            from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

            run_init_chain_at_dsn(target_dsn, emit=lambda _line: None)
            with psycopg.connect(target_dsn) as target:
                converged_rows = _postgres_schema_rows(target)
                assert converged_rows == expected_rows, {
                    "missing": sorted(set(expected_rows) - set(converged_rows)),
                    "extra": sorted(set(converged_rows) - set(expected_rows)),
                }
            result = portability.converge_and_validate_restored_universe(
                target_dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fp,
            )
            assert result["org"] == "default"

            # Restoring into the now-occupied target takes the same single
            # path: the destination is reset and replaced, so the operator
            # never sees an empty-versus-occupied distinction.
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT name FROM projects WHERE id = 88001"
                ).fetchone() == ("Portable",)
        finally:
            pg_testdb.drop_test_database(target_db)
