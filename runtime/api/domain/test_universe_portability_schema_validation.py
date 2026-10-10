"""Portable restore convergence and schema compatibility checks."""

import os
import psycopg
import pytest
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)
from runtime.api.domain.test_universe_portability import _canonical_test_universe
from yoke_contracts.timestamps import parse_instant


def test_restore_converges_known_older_schema_without_losing_data(tmp_path):
    from runtime.api.fixtures import pg_testdb

    stored_at = parse_instant("2026-08-12T09:10:11.123456Z")
    with _canonical_test_universe() as (source, source_dsn):
        with _canonical_test_universe() as (reference, _reference_dsn):
            expected_fp = fingerprint_portable_postgres_schema(reference)

        source.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (88101, 'portable-old', 'Portable Old', 'OLD', now())"
        )
        source.execute(
            "INSERT INTO github_app_installations "
            "(installation_id, account_id, account_login, account_type, "
            "repository_selection, permissions, status, created_at, updated_at) "
            "VALUES ('88102', '88103', 'example-org', 'Organization', "
            "'selected', '{}', 'active', %s, %s)",
            (stored_at, stored_at),
        )
        source.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, status, "
            "permissions, created_at, updated_at) "
            "VALUES (88101, '88102', '88104', 'example-org/portable-old', "
            "'active', '{}', %s, %s)",
            (stored_at, stored_at),
        )
        source.execute(
            "INSERT INTO project_onboarding_runs "
            "(run_id, schema_version, project_id, branch, status, metadata_json, "
            "created_at, updated_at) VALUES "
            "('portable-run', 1, 88101, 'local-checkout', 'open', '{}', "
            "%s, %s)",
            (stored_at, stored_at),
        )
        source.execute(
            "INSERT INTO project_onboarding_checklist_rows "
            "(run_id, row_id, step, title, layer, owner, status, evidence_json, "
            "updated_at) VALUES "
            "('portable-run', 'machine-profile', 'machine-profile', "
            "'Machine profile', 'machine', 'operator', 'verified', '{}', %s)",
            (stored_at,),
        )
        source.execute(
            "INSERT INTO qa_artifacts "
            "(id, qa_run_id, artifact_type, content_type, artifact_handle, "
            "metadata, created_at) VALUES "
            "(88105, NULL, 'screenshot', 'image/png', "
            "'artifact://legacy', '{}', %s)",
            (stored_at,),
        )
        source.execute(
            "ALTER TABLE project_github_repo_bindings DROP COLUMN last_sync_at"
        )
        source.execute(
            "ALTER TABLE project_github_repo_bindings DROP COLUMN last_sync_outcome"
        )
        source.execute(
            "ALTER TABLE project_github_repo_bindings DROP COLUMN last_sync_error"
        )
        source.execute(
            "ALTER TABLE qa_artifacts RENAME COLUMN artifact_handle TO storage_path"
        )
        source.commit()

        archive = tmp_path / "known-older-schema.dump"
        portability.dump_universe(source_dsn, archive)
        target_db = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_db)
        try:
            portability.restore_universe(archive, target_dsn)
            result = portability.converge_and_validate_restored_universe(
                target_dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fp,
            )
            assert result["org"] == "default"
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT artifact_handle, created_at FROM qa_artifacts WHERE id = 88105"
                ).fetchone() == ("artifact://legacy", stored_at)
                assert target.execute(
                    "SELECT last_sync_at, last_sync_outcome, last_sync_error "
                    "FROM project_github_repo_bindings WHERE project_id = 88101"
                ).fetchone() == (None, None, None)
                assert target.execute(
                    "SELECT COUNT(*) FROM project_onboarding_runs "
                    "WHERE run_id = 'portable-run'"
                ).fetchone() == (1,)
                assert target.execute(
                    "SELECT status, updated_at FROM project_onboarding_checklist_rows "
                    "WHERE run_id = 'portable-run' AND row_id = 'machine-profile'"
                ).fetchone() == ("verified", stored_at)
        finally:
            pg_testdb.drop_test_database(target_db)


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
