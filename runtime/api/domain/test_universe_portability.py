"""Portable-universe archive safety and round-trip tests."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from yoke_core.domain import universe_export
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import fingerprint_kind


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
        subprocess, "Popen",
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
    assert "\n1; 1259 1 TABLE public organizations" in rendered
    assert "\n;2; 1255 2 FUNCTION public run_on_seed()" in rendered
    assert "\n;3; 2620 3 TRIGGER public projects" in rendered

    unknown = catalog.replace("FUNCTION", "EXECUTABLE SURPRISE")
    with pytest.raises(portability.ArchiveInvalidError, match="unsupported"):
        portability._validate_catalog(unknown)

    foreign_schema = catalog.replace(
        "TABLE public organizations", "TABLE private organizations", 1,
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


def test_restore_pump_filters_only_the_version_compatibility_preamble():
    compatibility_line = b"SET transaction_timeout = 0;\n"
    source = io.BytesIO(
        b"-- PostgreSQL database dump\n"
        + compatibility_line
        + b"-- Name: sample; Type: TABLE DATA; Schema: public\n"
        # Identical bytes after the first object marker represent user data and
        # must never be globally rewritten.
        + compatibility_line
    )
    destination = io.BytesIO()
    errors: list[BaseException] = []
    portability._sql_pump(
        source, destination, max_sql_bytes=1024, errors=errors,
    )
    assert errors == []
    assert destination.getvalue() == (
        b"BEGIN;\n"
        b"-- PostgreSQL database dump\n"
        b"-- Name: sample; Type: TABLE DATA; Schema: public\n"
        + compatibility_line
    )


def test_restore_pump_bounds_expanded_archive_size():
    errors: list[BaseException] = []
    portability._sql_pump(
        io.BytesIO(
            b"-- Name: sample; Type: TABLE; Schema: public\n" + b"x" * 100
        ),
        io.BytesIO(),
        max_sql_bytes=32,
        errors=errors,
    )
    assert len(errors) == 1
    assert isinstance(errors[0], portability.ArchiveTooLargeError)


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
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_init import converge_core_schema

    with pg_testdb.test_database() as source:
        source_dsn = os.environ[db_backend.PG_DSN_ENV]
        converge_core_schema(source)
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

        source_info = psycopg.conninfo.conninfo_to_dict(source_dsn)
        admin_info = dict(source_info, dbname="postgres")
        target_db = "portability_executable_filter"
        with psycopg.connect(
            psycopg.conninfo.make_conninfo(**admin_info), autocommit=True,
        ) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{target_db}"')
            admin.execute(f'CREATE DATABASE "{target_db}"')
        target_dsn = psycopg.conninfo.make_conninfo(
            **dict(source_info, dbname=target_db),
        )
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
            with psycopg.connect(
                psycopg.conninfo.make_conninfo(**admin_info), autocommit=True,
            ) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = %s AND pid <> pg_backend_pid()",
                    (target_db,),
                )
                admin.execute(f'DROP DATABASE IF EXISTS "{target_db}"')


def test_restore_failure_is_one_transaction_and_round_trip_succeeds(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    # The public fixture owns an isolated cluster.  Create source and target
    # databases on that same cluster so pg_dump/pg_restore run for real.
    with pg_testdb.test_database() as source:
        source_dsn = os.environ[db_backend.PG_DSN_ENV]
        # The broad API fixture is intentionally a reduced test schema; bring
        # this source to the same full additive shape a real current local
        # universe carries before producing the portability artifact.
        from yoke_core.domain.schema_init import converge_core_schema
        from yoke_core.domain.flow_init import create_or_replace_item_progress_view

        converge_core_schema(source)
        create_or_replace_item_progress_view(source)
        source.commit()
        source.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (88001, 'portable', 'Portable', 'POR', now())"
        )
        source.commit()
        archive = Path(
            universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
        )

        source_info = psycopg.conninfo.conninfo_to_dict(source_dsn)
        admin_info = dict(source_info)
        admin_info["dbname"] = "postgres"
        target_db = "portability_round_trip"
        with psycopg.connect(
            psycopg.conninfo.make_conninfo(**admin_info), autocommit=True,
        ) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{target_db}"')
            admin.execute(f'CREATE DATABASE "{target_db}"')
        target_info = dict(source_info)
        target_info["dbname"] = target_db
        target_dsn = psycopg.conninfo.make_conninfo(**target_info)
        try:
            portability.restore_universe(archive, target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT name FROM projects WHERE id = 88001"
                ).fetchone() == ("Portable",)
                expected_fp = fingerprint_kind("postgres", source)
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
            with psycopg.connect(
                psycopg.conninfo.make_conninfo(**admin_info), autocommit=True,
            ) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = %s AND pid <> pg_backend_pid()",
                    (target_db,),
                )
                admin.execute(f'DROP DATABASE IF EXISTS "{target_db}"')


def test_schema_fingerprint_and_org_identity_fail_closed(tmp_path):
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        dsn = os.environ[db_backend.PG_DSN_ENV]
        expected = fingerprint_kind("postgres", conn)
        with pytest.raises(
            portability.ArchiveCompatibilityError, match="does not match",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="different-org",
                expected_schema_fingerprint=expected,
            )
        conn.execute("CREATE TABLE future_only_table (id bigint PRIMARY KEY)")
        conn.commit()
        with pytest.raises(
            portability.ArchiveCompatibilityError, match="not compatible",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected,
            )


def test_user_content_counts_detects_nonempty_universe():
    from runtime.api.fixtures import pg_testdb

    with pg_testdb.test_database() as conn:
        # The general API fixture carries two synthetic project rows; a newly
        # born product universe does not.  Remove fixture-only content before
        # asserting the portability definition of empty.
        conn.execute("DELETE FROM projects")
        conn.commit()
        assert all(value == 0 for value in portability.user_content_counts(conn).values())
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
