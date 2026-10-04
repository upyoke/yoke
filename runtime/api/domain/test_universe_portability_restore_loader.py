"""Portable archive streaming and restore syntax contracts."""

import io
import time
import pytest
from yoke_core.domain import universe_portability as portability


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
