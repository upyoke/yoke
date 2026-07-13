"""Portable-universe archive safety and round-trip tests."""

from __future__ import annotations

import io
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from yoke_core.domain import universe_export
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


def test_postgres_client_env_keeps_credentials_out_of_argv_env_shape():
    env = portability.postgres_client_env(
        "postgresql://alice:p%40ss@db.example:5433/yoke"
        "?sslmode=verify-full&sslrootcert=%2Fca.pem",
        base={"PATH": "/bin", "PGDATABASE": "ambient", "YOKE_PG_DSN": "leak"},
    )
    assert env["PGUSER"] == "alice"
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGHOST"] == "db.example"
    assert env["PGPORT"] == "5433"
    assert env["PGDATABASE"] == "yoke"
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGSSLROOTCERT"] == "/ca.pem"
    assert "YOKE_PG_DSN" not in env


def test_inspection_rejects_huge_body_before_subprocess(tmp_path, monkeypatch):
    archive = tmp_path / "huge.dump"
    archive.write_bytes(portability.ARCHIVE_MAGIC + b"x" * 20)
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("pg_restore must not run")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(portability.ArchiveTooLargeError):
        portability.inspect_archive(archive, max_bytes=10)
    assert called is False


def test_inspection_rejects_bad_magic_without_spawning(tmp_path, monkeypatch):
    archive = tmp_path / "tampered.dump"
    archive.write_bytes(b"NOT-A-DUMP")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pg_restore must not run")
        ),
    )
    with pytest.raises(portability.ArchiveInvalidError, match="custom-format"):
        portability.inspect_archive(archive)


def test_inspection_rejects_cluster_objects_and_timeout(tmp_path, monkeypatch):
    archive = tmp_path / "catalog.dump"
    archive.write_bytes(portability.ARCHIVE_MAGIC + b"placeholder")
    catalog = """;
;     Dumped from database version: 17.10
;     Dumped by pg_dump version: 17.10
1; 1259 1 TABLE public organizations yoke
2; 3079 2 EXTENSION - dblink
"""
    with pytest.raises(portability.ArchiveInvalidError, match="EXTENSION"):
        portability._validate_catalog(catalog)

    class TimedOutCatalog:
        def __init__(self, *_args, **_kwargs):
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.returncode = None

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired(["pg_restore"], timeout)
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", TimedOutCatalog)
    with pytest.raises(portability.ArchiveInvalidError, match="timed out"):
        portability.inspect_archive(archive, timeout_s=1)


def test_catalog_allowlist_omits_executable_schema_and_refuses_unknown(tmp_path):
    catalog = """;
;     Dumped from database version: 17.10
;     Dumped by pg_dump version: 17.10
1; 1259 1 TABLE public organizations yoke
2; 1255 2 FUNCTION public run_on_seed() yoke
3; 2620 3 TRIGGER public projects dangerous yoke
4; 0 4 TABLE DATA public organizations yoke
"""
    assert portability._validate_catalog(catalog) == 2
    restore_list = portability._write_restore_list(catalog)
    try:
        rendered = restore_list.read_text(encoding="utf-8")
    finally:
        restore_list.unlink()
    assert "\n;1; 1259 1 TABLE public organizations" in rendered
    assert "\n;2; 1255 2 FUNCTION public run_on_seed()" in rendered
    assert "\n;3; 2620 3 TRIGGER public projects" in rendered
    assert "\n4; 0 4 TABLE DATA public organizations" in rendered

    unknown = catalog.replace("FUNCTION", "EXECUTABLE SURPRISE")
    with pytest.raises(portability.ArchiveInvalidError, match="unsupported"):
        portability._validate_catalog(unknown)

    foreign_schema = catalog.replace(
        "TABLE public organizations",
        "TABLE private organizations",
        1,
    )
    with pytest.raises(portability.ArchiveInvalidError, match="outside public"):
        portability._validate_catalog(foreign_schema)


def test_catalog_reader_has_a_hard_memory_ceiling(monkeypatch):
    monkeypatch.setattr(portability, "_CATALOG_BYTES", 5)
    sink = bytearray()
    errors: list[BaseException] = []
    portability._catalog_reader(io.BytesIO(b"123456"), sink, errors)
    assert sink == b""
    assert len(errors) == 1
    assert isinstance(errors[0], portability.ArchiveInvalidError)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _CopySink:
    def __init__(self):
        self.body = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, chunk):
        self.body.extend(chunk)


class _Cursor:
    def __init__(self, owner):
        self.owner = owner

    def copy(self, statement):
        self.owner.copy_statement = statement
        return self.owner.copy_sink


class _RestoreConn:
    def __init__(self):
        self.copy_sink = _CopySink()
        self.copy_statement = None
        self.setvals = []

    def execute(self, statement, params=None):
        rendered = str(statement)
        if "pg_catalog.pg_class" in rendered:
            return _Rows([("sample", "id"), ("sample", "body")])
        if "pg_catalog.pg_sequences" in rendered:
            return _Rows([("sample_id_seq",)])
        self.setvals.append(params)
        return _Rows([])

    def cursor(self):
        return _Cursor(self)


def _apply_sample_restore(
    body: bytes,
    *,
    max_sql_bytes: int = 4096,
    allowed_tables=None,
    allowed_sequences=None,
):
    conn = _RestoreConn()
    portability._apply_restore_stream(
        io.BytesIO(body),
        conn,
        allowed_tables={"sample"} if allowed_tables is None else allowed_tables,
        allowed_sequences=(
            {"sample_id_seq"} if allowed_sequences is None else allowed_sequences
        ),
        max_sql_bytes=max_sql_bytes,
        deadline=time.monotonic() + 10,
    )
    return conn


def test_restore_loader_discards_compatibility_preamble_and_uses_copy_api():
    conn = _apply_sample_restore(
        b"-- PostgreSQL database dump\n"
        b"SET transaction_timeout = 0;\n"
        b"SELECT pg_catalog.set_config('search_path', '', false);\n"
        b"COPY public.sample (id, body) FROM stdin;\n"
        b"1\tSET transaction_timeout = 0;\n"
        b"\\.\n"
        b"SELECT pg_catalog.setval('public.sample_id_seq', 1, true);\n"
    )
    assert conn.copy_sink.body == b"1\tSET transaction_timeout = 0;\n"
    assert conn.copy_statement is not None
    assert conn.setvals == [("public.sample_id_seq", 1, True)]


def test_restore_loader_accepts_catalog_columns_in_archive_order():
    conn = _apply_sample_restore(
        b"COPY public.sample (body, id) FROM stdin;\n"
        b"trusted body\t1\n"
        b"\\.\n"
        b"SELECT pg_catalog.setval('public.sample_id_seq', 1, true);\n"
    )
    assert conn.copy_sink.body == b"trusted body\t1\n"
    assert "body" in str(conn.copy_statement)
    assert "id" in str(conn.copy_statement)


def test_restore_column_compatibility_is_explicit_and_fail_closed():
    assert portability._compatible_restore_columns(
        "sample", ("body", "id"), ("id", "body")
    ) == ("body", "id")
    assert portability._compatible_restore_columns(
        "qa_artifacts",
        ("id", "storage_path"),
        ("id", "artifact_handle"),
    ) == ("id", "artifact_handle")
    assert portability._compatible_restore_columns(
        "project_github_repo_bindings",
        ("project_id",),
        ("project_id", "last_sync_at", "last_sync_outcome", "last_sync_error"),
    ) == ("project_id",)

    with pytest.raises(portability.ArchiveCompatibilityError, match="unknown"):
        portability._compatible_restore_columns(
            "sample", ("id", "surprise"), ("id", "body")
        )
    with pytest.raises(portability.ArchiveCompatibilityError, match="missing"):
        portability._compatible_restore_columns("sample", ("id",), ("id", "body"))


@pytest.mark.parametrize(
    "injected",
    (b"COMMIT;\n", b"ALTER DATABASE postgres RENAME TO stolen;\n", b"\\! id\n"),
)
def test_restore_loader_rejects_executable_or_psql_syntax(injected):
    with pytest.raises(portability.ArchiveInvalidError, match="executable"):
        _apply_sample_restore(injected)


def test_restore_loader_rejects_catalog_mismatch_and_expansion():
    with pytest.raises(portability.ArchiveInvalidError, match="does not match"):
        _apply_sample_restore(b"-- no table data\n")
    with pytest.raises(portability.ArchiveCompatibilityError, match="catalog"):
        _apply_sample_restore(
            b"-- no table data\n",
            allowed_tables=set(),
        )
    with pytest.raises(portability.ArchiveCompatibilityError, match="catalog"):
        _apply_sample_restore(
            b"-- no sequence data\n",
            allowed_sequences=set(),
        )
    with pytest.raises(portability.ArchiveCompatibilityError, match="extra"):
        _apply_sample_restore(
            b"-- no table data\n",
            allowed_tables={"sample", "surprise"},
        )
    with pytest.raises(portability.ArchiveTooLargeError):
        _apply_sample_restore(
            b"COPY public.sample (id, body) FROM stdin;\n" + b"x" * 100,
            max_sql_bytes=32,
        )


@pytest.mark.parametrize(
    "body, match",
    (
        (
            b"COPY public.sample (id) FROM stdin;\n1\n\\.\n",
            "columns",
        ),
        (
            b"COPY private.sample (id, body) FROM stdin;\n1\tx\n\\.\n",
            "target",
        ),
        (
            b"COPY public.sample (id, body) FROM stdin;\n1\tx\n\\.\nCOMMIT;\n",
            "executable",
        ),
        (
            b"COPY public.sample (id, body) FROM stdin;\n1\tx\n",
            "terminator",
        ),
    ),
)
def test_restore_loader_rejects_incomplete_or_injected_copy(body, match):
    with pytest.raises(portability.UniversePortabilityError, match=match):
        _apply_sample_restore(body)


def test_restore_loader_streams_a_row_larger_than_one_chunk():
    row = b"1\t" + b"x" * (portability._PUMP_CHUNK_BYTES + 17) + b"\n"
    conn = _apply_sample_restore(
        b"COPY public.sample (id, body) FROM stdin;\n"
        + row
        + b"\\.\n"
        + b"SELECT pg_catalog.setval('public.sample_id_seq', 1, true);\n",
        max_sql_bytes=len(row) + 4096,
    )
    assert conn.copy_sink.body == row


def test_inspection_rejects_tampered_real_archive(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database():
        dsn = os.environ[db_backend.PG_DSN_ENV]
        artifact = Path(
            universe_export.export_universe(dsn=dsn, out=tmp_path)["artifact"]
        )
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
            "INSERT INTO items "
            "(id, title, type, status, priority, created_at, updated_at, "
            "project_id, project_sequence, resolution, resolution_ref, "
            "resolution_comment, design_spec) VALUES "
            "(88003, 'Closed item', 'issue', 'cancelled', 'medium', now(), now(), "
            "88001, 1, 'duplicate', 'POR-2', 'Preserve close history', "
            "'trusted body')"
        )
        source.commit()
        archive = Path(
            universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
        )

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

            # A restore into the now-nonempty target fails in its single
            # transaction; the first successful data remains intact.
            with pytest.raises(portability.UniversePortabilityError):
                portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT name FROM projects WHERE id = 88001"
                ).fetchone() == ("Portable",)
        finally:
            pg_testdb.drop_test_database(target_db)


def test_restore_converges_known_older_schema_without_losing_data(tmp_path):
    from runtime.api.fixtures import pg_testdb

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
            "'selected', '{}', 'active', 'then', 'then')"
        )
        source.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, status, "
            "permissions, created_at, updated_at) "
            "VALUES (88101, '88102', '88104', 'example-org/portable-old', "
            "'active', '{}', 'then', 'then')"
        )
        source.execute(
            "INSERT INTO project_onboarding_runs "
            "(run_id, schema_version, project_id, branch, status, metadata_json, "
            "created_at, updated_at) VALUES "
            "('portable-run', 1, 88101, 'local-checkout', 'open', '{}', "
            "'then', 'then')"
        )
        source.execute(
            "INSERT INTO project_onboarding_checklist_rows "
            "(run_id, row_id, step, title, layer, owner, status, evidence_json, "
            "updated_at) VALUES "
            "('portable-run', 'machine-profile', 'machine-profile', "
            "'Machine profile', 'machine', 'operator', 'verified', '{}', 'then')"
        )
        source.execute(
            "INSERT INTO qa_artifacts "
            "(id, qa_run_id, artifact_type, content_type, artifact_handle, "
            "metadata, created_at) VALUES "
            "(88105, NULL, 'screenshot', 'image/png', "
            "'artifact://legacy', '{}', 'then')"
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
                    "SELECT artifact_handle FROM qa_artifacts WHERE id = 88105"
                ).fetchone() == ("artifact://legacy",)
                assert target.execute(
                    "SELECT last_sync_at, last_sync_outcome, last_sync_error "
                    "FROM project_github_repo_bindings WHERE project_id = 88101"
                ).fetchone() == (None, None, None)
                assert target.execute(
                    "SELECT COUNT(*) FROM project_onboarding_runs "
                    "WHERE run_id = 'portable-run'"
                ).fetchone() == (1,)
                assert target.execute(
                    "SELECT status FROM project_onboarding_checklist_rows "
                    "WHERE run_id = 'portable-run' AND row_id = 'machine-profile'"
                ).fetchone() == ("verified",)
        finally:
            pg_testdb.drop_test_database(target_db)


def test_schema_fingerprint_and_org_identity_fail_closed(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        dsn = os.environ[db_backend.PG_DSN_ENV]
        expected = fingerprint_portable_postgres_schema(conn)
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


def test_user_content_counts_detects_nonempty_universe():
    with _canonical_test_universe() as (conn, _dsn):
        # The general API fixture carries two synthetic project rows; a newly
        # born product universe does not.  Remove fixture-only content before
        # asserting the portability definition of empty.
        conn.execute("DELETE FROM api_token_audit")
        conn.execute("DELETE FROM api_tokens")
        conn.execute("DELETE FROM projects")
        conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, tables_declared, expected_deltas, pre_row_counts, "
            "backup_path, state, started_at) VALUES "
            "('maintenance-receipt', '[]', '{}', '{}', 'none', 'completed', now())"
        )
        conn.commit()
        empty_counts = portability.user_content_counts(conn)
        assert "migration_audit" not in empty_counts
        assert all(value == 0 for value in empty_counts.values())
        actor_id = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO api_tokens "
            "(id, token_hash, actor_id, name, status, created_at) "
            "VALUES (99000, 'credential-only', %s, 'extra', 'active', now())",
            (actor_id,),
        )
        conn.commit()
        assert portability.user_content_counts(conn)["api_tokens"] == 1
        conn.execute("DELETE FROM api_tokens WHERE id = 99000")
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (99001, 'not-empty', 'Not Empty', 'NON', now())"
        )
        counts = portability.user_content_counts(conn)
        assert counts["projects"] == 1

        conn.execute("DELETE FROM projects WHERE id = 99001")
        conn.execute(
            "INSERT INTO ouroboros_entries"
            " (id, timestamp, agent, category, body, created_at, project_id)"
            " VALUES (99002, 'now', 'tester', 'observation', 'real work',"
            " 'now', NULL)"
        )
        conn.commit()
        counts = portability.user_content_counts(conn)
        assert counts["ouroboros_entries"] == 1

        conn.execute(
            "INSERT INTO project_onboarding_runs "
            "(run_id, schema_version, branch, status, metadata_json, created_at, "
            "updated_at) VALUES "
            "('content-run', 1, 'local-checkout', 'open', '{}', 'now', 'now')"
        )
        conn.commit()
        counts = portability.user_content_counts(conn)
        assert counts["project_onboarding_runs"] == 1

        conn.execute("CREATE TABLE future_content (id integer primary key)")
        conn.execute("INSERT INTO future_content (id) VALUES (1)")
        conn.commit()
        assert portability.all_table_row_counts(conn)["future_content"] == 1
