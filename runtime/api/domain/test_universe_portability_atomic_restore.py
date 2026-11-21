"""A failed universe replacement leaves its live schema and files intact."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from contextlib import ExitStack

import psycopg
import pytest
from psycopg import sql

from runtime.api.domain.universe_portability_test_support import _canonical_test_universe
from yoke_core.domain import environment_bootstrap, machine_config
from yoke_core.domain import universe_portability as portability
from yoke_core.domain import universe_portability_restore_transaction as transaction
from yoke_core.domain.schema_fingerprint_postgres_rows import _postgres_schema_rows
from yoke_core.domain.shared_file_storage import put_shared_file, read_shared_file
from yoke_core.domain.universe_archive_artifacts import MANIFEST
from yoke_core.domain.universe_artifact_transfer import restore_artifacts
from yoke_core.domain.universe_portability_restore_schema import (
    IMPORT_SCHEMA,
    bounded_dsn,
    publish_restore_schema,
)

_ARCHIVE_PROJECT_ID = 7401
_PROJECT_SQL = (
    "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
    "VALUES (%s, %s, %s, 'ATM', now())"
)
_PUBLIC_METADATA_SQL = (
    "SELECT nspowner, nspacl::text, obj_description(oid, 'pg_namespace') "
    "FROM pg_namespace WHERE nspname = 'public'"
)


@pytest.fixture
def archived_universe(tmp_path):
    with _canonical_test_universe() as (source, source_dsn):
        source.execute(_PROJECT_SQL, (_ARCHIVE_PROJECT_ID, "atom", "archive-private-value"))
        source.commit()
        archive = tmp_path / "universe.dump"
        portability.dump_universe(source_dsn, archive)
        return archive


@pytest.fixture
def destination():
    with _canonical_test_universe() as (conn, dsn):
        conn.execute(_PROJECT_SQL, (9001, "atom", "previous-universe"))
        conn.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        conn.commit()
        yield conn, dsn


def _catalog(conn):
    namespace = conn.execute("SELECT current_schema()").fetchone()[0]
    return [
        (kind, name, definition.replace(f"{namespace}.", "public."))
        for kind, name, definition in _postgres_schema_rows(conn)
    ]


def _state(conn):
    tables = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    ).fetchall()
    sequences = conn.execute(
        "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' ORDER BY sequencename"
    ).fetchall()
    counts = [
        conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()
        for (table,) in tables
    ]
    sequence_values = [
        conn.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(
            sql.Identifier(sequence)
        )).fetchone()
        for (sequence,) in sequences
    ]
    return _catalog(conn), counts, sequence_values, conn.execute(_PUBLIC_METADATA_SQL).fetchone()


def _shared_manifest(archive):
    key = "shared-files/atom/example.txt"
    source = archive.parent / "artifacts" / key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new bytes")
    (archive.parent / MANIFEST).write_text(json.dumps({"entries": [{
        "key": key,
        "project": "atom",
        "status": "included",
        "original_handle": {"backend": "local", "path": str(source)},
    }]}))


@pytest.mark.parametrize(("phase", "diagnostic"), [
    ("init", r"initialization failed.*RuntimeError.*init fault"),
    ("copy", r"COPY for projects.*UniqueViolation.*23505"),
    ("setval", r"setval for .*NumericValueOutOfRange.*22003"),
    ("finalize", "finalize fault"),
    ("swap", r"schema swap failed.*LockNotAvailable.*55P03.*lock timeout"),
])
def test_failure_preserves_live_universe(
    archived_universe, destination, phase, diagnostic, monkeypatch, tmp_path,
):
    conn, dsn = destination
    monkeypatch.setattr(machine_config, "yoke_home", lambda: tmp_path / "destination-store")
    old_file = put_shared_file(
        conn, project_id=9001, project="atom", path="example.txt", content=b"old bytes",
    )
    _shared_manifest(archived_universe)
    before = _state(conn)
    conn.commit()

    def broken_init(_dsn, **_kwargs):
        raise RuntimeError("init fault")

    if phase == "init":
        monkeypatch.setattr(environment_bootstrap, "run_init_chain_at_dsn", broken_init)

    if phase in {"copy", "setval"}:
        apply = transaction.apply_restore_stream

        def fault_stream(source, target, **kwargs):
            if phase == "copy":
                target.execute(
                    _PROJECT_SQL, (_ARCHIVE_PROJECT_ID, "staged-only", "collision-private-value"),
                )
            else:
                sequence = min(kwargs["allowed_sequences"])
                target.execute(sql.SQL("ALTER SEQUENCE {} MINVALUE 1000000000 START WITH 1000000000 RESTART WITH 1000000000")
                               .format(sql.Identifier(sequence)))
            return apply(source, target, **kwargs)

        monkeypatch.setattr(transaction, "apply_restore_stream", fault_stream)

    def finalize(target):
        restore_artifacts(target, archived_universe, {})
        if phase == "finalize":
            raise RuntimeError("finalize fault")

    with ExitStack() as stack:
        if phase == "swap":
            lock_holder = stack.enter_context(psycopg.connect(dsn))
            lock_holder.execute("LOCK TABLE items IN ACCESS SHARE MODE")

            def short_swap_timeout(target, schema):
                target.execute("SET LOCAL lock_timeout = '100ms'")
                publish_restore_schema(target, schema)

            monkeypatch.setattr(transaction, "publish_restore_schema", short_swap_timeout)
        error_type = RuntimeError if phase == "finalize" else portability.UniversePortabilityError
        with pytest.raises(error_type, match=diagnostic) as refused:
            portability.restore_universe(archived_universe, dsn, finalize=finalize)

    refusal = str(refused.value)
    assert "archive-private-value" not in refusal
    assert "collision-private-value" not in refusal
    assert "DETAIL:" not in refusal
    assert "CONTEXT:" not in refusal
    assert _state(conn) == before
    assert conn.execute("SELECT to_regnamespace(%s)", (IMPORT_SCHEMA,)).fetchone() == (None,)
    assert read_shared_file(conn, project_id=9001, project="atom", path="example.txt") == b"old bytes"
    assert Path(old_file.address).read_bytes() == b"old bytes"


def test_import_loads_while_public_accepts_writes(archived_universe, destination, monkeypatch):
    conn, dsn = destination
    public_acl = conn.execute(_PUBLIC_METADATA_SQL).fetchone()
    project_query = "SELECT id, name FROM projects"
    assert conn.execute(project_query, prepare=True).fetchall() == [
        (9001, "previous-universe")
    ]
    conn.commit()
    writer_ready = threading.Event()
    writer_stop = threading.Event()
    writer_errors = []
    wrote_to_public = threading.Event()
    apply = transaction.apply_restore_stream

    def observe_load(*args, **kwargs):
        writer_ready.set()
        assert wrote_to_public.wait(timeout=10), "live writer did not commit its colliding row"
        return apply(*args, **kwargs)

    def write_to_public():
        try:
            if not writer_ready.wait(timeout=10):
                raise AssertionError("restore did not start loading")
            with psycopg.connect(dsn, autocommit=True) as writer:
                writer.execute(_PROJECT_SQL, (_ARCHIVE_PROJECT_ID, "writer", "live collision"))
                while not writer_stop.is_set():
                    writer.execute(
                        "UPDATE projects SET name = name || '.' WHERE id = %s",
                        (_ARCHIVE_PROJECT_ID,),
                    )
                    wrote_to_public.set()
        except Exception as error:
            writer_errors.append(error)

    worker = threading.Thread(target=write_to_public, daemon=True)

    def finalize(_target):
        writer_stop.set()
        worker.join(timeout=10)
        assert not worker.is_alive()

    monkeypatch.setattr(transaction, "apply_restore_stream", observe_load)
    worker.start()
    try:
        portability.restore_universe(archived_universe, dsn, finalize=finalize)
    finally:
        writer_stop.set()
        worker.join(timeout=10)
    assert not writer_errors
    assert wrote_to_public.is_set()
    assert conn.execute(project_query, prepare=True).fetchall() == [
        (_ARCHIVE_PROJECT_ID, "archive-private-value")
    ]
    assert conn.execute(_PUBLIC_METADATA_SQL).fetchone() == public_acl


def test_init_chain_builds_same_catalog_alongside_populated_public(destination):
    conn, dsn = destination
    namespace = "alternate_universe"
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
    conn.commit()
    alternate_dsn = bounded_dsn(dsn, 30, namespace)
    environment_bootstrap.run_init_chain_at_dsn(alternate_dsn, emit=lambda _line: None)
    with psycopg.connect(alternate_dsn) as alternate:
        assert _catalog(alternate) == _catalog(conn)
