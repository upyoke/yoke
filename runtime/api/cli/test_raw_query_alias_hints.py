"""Alias-aware SQL hint regression tests.

Exercises `yoke_core.cli.raw_query._schema_hint` against real Postgres
schemas so the `column <alias>.<col> does not exist` wrapper proves it
resolves the alias back to the joined table rather than guessing one table
from the join.
"""

from __future__ import annotations

import io

from yoke_core.cli import raw_query
from yoke_core.domain import db_backend


def _pg_conn():
    import psycopg

    return psycopg.connect(db_backend.resolve_pg_dsn())


def _make_conn():
    conn = _pg_conn()
    conn.execute(
        """
        CREATE TEMP TABLE path_targets (
            id INTEGER PRIMARY KEY,
            path_string TEXT,
            kind TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE path_claims (
            id INTEGER PRIMARY KEY,
            state TEXT,
            actor_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT
        )
        """
    )
    conn.commit()
    return conn


# ---------- _extract_table_refs ---------------------------------------------


def test_extract_table_refs_with_as_alias():
    refs = raw_query._extract_table_refs(
        "SELECT pt.id FROM path_targets AS pt"
    )
    assert refs == [("path_targets", "pt")]


def test_extract_table_refs_with_bare_alias():
    refs = raw_query._extract_table_refs(
        "SELECT pt.id FROM path_targets pt"
    )
    assert refs == [("path_targets", "pt")]


def test_extract_table_refs_join_multiple_aliases():
    refs = raw_query._extract_table_refs(
        "SELECT pt.id, pc.state FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id"
    )
    assert refs == [("path_targets", "pt"), ("path_claims", "pc")]


def test_extract_table_refs_no_alias_then_join():
    refs = raw_query._extract_table_refs(
        "SELECT * FROM items JOIN path_claims pc ON pc.id = items.id"
    )
    assert refs == [("items", None), ("path_claims", "pc")]


def test_extract_table_refs_treats_sql_keyword_as_no_alias():
    # `WHERE` after the table is a clause start, not an alias.
    refs = raw_query._extract_table_refs(
        "SELECT * FROM items WHERE status = 'done'"
    )
    assert refs == [("items", None)]


def test_extract_table_refs_inner_left_keywords_not_aliases():
    refs = raw_query._extract_table_refs(
        "SELECT * FROM items INNER JOIN path_claims ON path_claims.id = items.id"
    )
    assert refs == [("items", None), ("path_claims", None)]


# ---------- _resolve_alias ---------------------------------------------------


def test_resolve_alias_matches_alias_first():
    refs = [("path_targets", "pt"), ("path_claims", "pc")]
    assert raw_query._resolve_alias(refs, "pt") == "path_targets"
    assert raw_query._resolve_alias(refs, "pc") == "path_claims"


def test_resolve_alias_falls_back_to_table_name():
    refs = [("path_targets", "pt")]
    assert raw_query._resolve_alias(refs, "path_targets") == "path_targets"


def test_resolve_alias_returns_none_for_unknown():
    refs = [("path_targets", "pt")]
    assert raw_query._resolve_alias(refs, "zz") is None


def test_resolve_alias_is_case_insensitive():
    refs = [("path_targets", "PT")]
    assert raw_query._resolve_alias(refs, "pt") == "path_targets"


# ---------- _schema_hint end-to-end -----------------------------------------


def test_hint_alias_resolves_to_correct_join_table():
    conn = _make_conn()
    exc = RuntimeError("column pt.posix_path does not exist")
    sql = (
        "SELECT pt.id FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id"
    )
    hint = raw_query._schema_hint(conn, sql, exc)
    assert hint.startswith("Valid columns on path_targets:")
    # The hint must NOT list columns of the wrong joined table.
    assert "path_claims" not in hint


def test_hint_alias_pointing_at_second_join_table():
    conn = _make_conn()
    exc = RuntimeError("column pc.posix_path does not exist")
    sql = (
        "SELECT pc.id FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id"
    )
    hint = raw_query._schema_hint(conn, sql, exc)
    assert hint.startswith("Valid columns on path_claims:")
    assert "path_targets" not in hint


def test_hint_unresolved_alias_lists_all_joined_tables():
    conn = _make_conn()
    exc = RuntimeError("column zz.posix_path does not exist")
    sql = (
        "SELECT * FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id"
    )
    hint = raw_query._schema_hint(conn, sql, exc)
    # Both joined tables must surface so the operator can locate the column.
    assert "Valid columns on path_targets:" in hint
    assert "Valid columns on path_claims:" in hint


def test_hint_no_prefix_multi_table_lists_each():
    conn = _make_conn()
    exc = RuntimeError("column posix_path does not exist")
    sql = (
        "SELECT * FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id"
    )
    hint = raw_query._schema_hint(conn, sql, exc)
    assert "Valid columns on path_targets:" in hint
    assert "Valid columns on path_claims:" in hint


def test_hint_single_table_preserves_legacy_behavior():
    conn = _make_conn()
    exc = RuntimeError("column posix_path does not exist")
    sql = "SELECT * FROM items"
    hint = raw_query._schema_hint(conn, sql, exc)
    assert hint.startswith("Valid columns on items:")


def test_hint_table_name_prefix_resolves_directly():
    # Using the literal table name as the prefix (no alias declared).
    conn = _make_conn()
    exc = RuntimeError("column items.unknown does not exist")
    sql = "SELECT items.unknown FROM items JOIN path_claims ON 1=1"
    hint = raw_query._schema_hint(conn, sql, exc)
    assert hint.startswith("Valid columns on items:")
    assert "path_claims" not in hint


def test_hint_no_such_table_unchanged():
    conn = _make_conn()
    exc = RuntimeError('relation "ghost" does not exist')
    sql = "SELECT * FROM ghost"
    hint = raw_query._schema_hint(conn, sql, exc)
    assert hint.startswith("Valid tables:")


# ---------- execute_query integration ---------------------------------------


def test_execute_query_emits_alias_hint_on_unknown_column(tmp_path):
    """End-to-end: a real failing query against a real on-disk DB lists
    the alias-resolved table columns in the stderr hint."""
    out = io.StringIO()
    err = io.StringIO()
    rc = raw_query.execute_query(
        "SELECT pt.posix_path FROM path_targets AS pt "
        "JOIN path_claims pc ON pc.id = pt.id",
        db_path=str(tmp_path / "retired.db"),
        out=out,
        err=err,
    )
    assert rc == 1
    err_text = err.getvalue()
    assert (
        "no such column: pt.posix_path" in err_text
        or "column pt.posix_path does not exist" in err_text
    )
    assert "Valid columns on path_targets:" in err_text
    # The hint must not advertise path_claims as the home for pt.<col>.
    assert "Valid columns on path_claims:" not in err_text
