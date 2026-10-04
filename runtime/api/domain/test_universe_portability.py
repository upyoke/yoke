"""Archive inspection safety and canonical test-universe setup."""

import io
import subprocess
from contextlib import contextmanager
import psycopg
import pytest
from yoke_core.domain import universe_portability as portability


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

    secret_data = catalog.replace(
        "TABLE DATA public organizations",
        "TABLE DATA public capability_secrets",
    )
    with pytest.raises(portability.ArchiveInvalidError, match="secret data"):
        portability._validate_catalog(secret_data)

    secret_sequence = catalog.replace(
        "4; 0 4 TABLE DATA public organizations yoke",
        "4; 0 4 TABLE DATA public organizations yoke\n"
        "5; 0 5 SEQUENCE SET public capability_secrets_id_seq yoke",
    )
    with pytest.raises(portability.ArchiveInvalidError, match="secret sequence"):
        portability._validate_catalog(secret_sequence)


def test_catalog_reader_has_a_hard_memory_ceiling(monkeypatch):
    monkeypatch.setattr(portability, "_CATALOG_BYTES", 5)
    sink = bytearray()
    errors: list[BaseException] = []
    portability._catalog_reader(io.BytesIO(b"123456"), sink, errors)
    assert sink == b""
    assert len(errors) == 1
    assert isinstance(errors[0], portability.ArchiveInvalidError)
