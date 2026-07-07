"""Regression tests for the mechanical DB-mutation compatibility scanner.

Every SQLite banned pattern in §6.1b has a test proving a ``pre_merge_safe``
declaration would escalate to ``pre_merge_breaking`` once the scanner
fires.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.db_mutation_compat_scanner import (
    ScannerHit,
    UnsupportedDbKindError,
    has_banned_pattern,
    scan,
    supported_kinds,
)


KIND = "sqlite_file"


class TestDispatchRegistry:
    def test_supported_kinds_exposes_sqlite(self) -> None:
        assert KIND in supported_kinds()

    def test_unsupported_kind_raises(self) -> None:
        # Dispatches by authoritative_db.kind; future backends add
        # their own rulesets.  An unknown kind fails loudly.
        with pytest.raises(UnsupportedDbKindError):
            scan("DROP TABLE items;", authoritative_db_kind="cassandra")

    def test_empty_ddl_returns_no_hits(self) -> None:
        assert scan("", authoritative_db_kind=KIND) == []
        assert scan("\n\n  -- just a comment\n", authoritative_db_kind=KIND) == []


def _ids(hits):
    return [h.pattern_id for h in hits]


class TestSqliteBannedPatterns:
    """AC-32 + AC-69: every banned SQLite pattern is caught."""

    def test_drop_table(self) -> None:
        hits = scan("DROP TABLE items;", authoritative_db_kind=KIND)
        assert _ids(hits) == ["sqlite.drop_table"]

    def test_drop_table_if_exists(self) -> None:
        hits = scan("DROP TABLE IF EXISTS items;", authoritative_db_kind=KIND)
        assert _ids(hits) == ["sqlite.drop_table"]

    def test_drop_column(self) -> None:
        hits = scan(
            "ALTER TABLE items DROP COLUMN legacy_col;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.drop_column"]

    def test_drop_column_without_column_keyword(self) -> None:
        # SQLite supports ``ALTER TABLE ... DROP <colname>`` without the
        # explicit COLUMN token.  Scanner catches both.
        hits = scan(
            "ALTER TABLE items DROP legacy_col;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.drop_column"]

    def test_drop_index(self) -> None:
        hits = scan(
            "DROP INDEX idx_items_status;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.drop_index"]

    def test_rename_column(self) -> None:
        hits = scan(
            "ALTER TABLE items RENAME COLUMN old_name TO new_name;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.rename_column"]

    def test_rename_table(self) -> None:
        hits = scan(
            "ALTER TABLE old_items RENAME TO items;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.rename_table"]

    def test_add_column_not_null_no_default(self) -> None:
        hits = scan(
            "ALTER TABLE items ADD COLUMN new_col TEXT NOT NULL;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.add_column_not_null_no_default"]

    def test_add_column_not_null_with_default_is_safe(self) -> None:
        # The scanner MUST NOT flag ADD COLUMN ... NOT NULL DEFAULT — the
        # existing-row story is resolved by the default.
        hits = scan(
            "ALTER TABLE items ADD COLUMN new_col TEXT NOT NULL DEFAULT '';",
            authoritative_db_kind=KIND,
        )
        assert hits == []

    def test_add_nullable_column_is_safe(self) -> None:
        # Nullable additions are additive-schema; scanner lets them through.
        hits = scan(
            "ALTER TABLE items ADD COLUMN new_col TEXT;",
            authoritative_db_kind=KIND,
        )
        assert hits == []

    def test_create_unique_index(self) -> None:
        hits = scan(
            "CREATE UNIQUE INDEX idx_items_title ON items(title);",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.create_unique_index"]

    def test_create_non_unique_index_is_safe(self) -> None:
        hits = scan(
            "CREATE INDEX idx_items_title ON items(title);",
            authoritative_db_kind=KIND,
        )
        assert hits == []

    def test_delete_without_where(self) -> None:
        hits = scan(
            "DELETE FROM items;",
            authoritative_db_kind=KIND,
        )
        assert _ids(hits) == ["sqlite.delete_no_where"]

    def test_delete_with_where_is_safe(self) -> None:
        # DELETE with WHERE is a targeted mutation; scanner lets it through.
        hits = scan(
            "DELETE FROM items WHERE status = 'cancelled';",
            authoritative_db_kind=KIND,
        )
        assert hits == []


class TestScannerMetadata:
    def test_hits_carry_pattern_id_and_reason(self) -> None:
        hits = scan("DROP TABLE items;", authoritative_db_kind=KIND)
        assert len(hits) == 1
        hit = hits[0]
        assert isinstance(hit, ScannerHit)
        assert hit.pattern_id == "sqlite.drop_table"
        assert "pre_merge_breaking" in hit.reason

    def test_line_numbers_are_one_indexed(self) -> None:
        ddl = "\n\nDROP TABLE items;\n"
        hits = scan(ddl, authoritative_db_kind=KIND)
        assert len(hits) == 1
        # statement begins on line 3 (0-indexed position → 1-indexed line)
        assert hits[0].line_number == 3

    def test_case_insensitive(self) -> None:
        hits = scan("drop table Items;", authoritative_db_kind=KIND)
        assert _ids(hits) == ["sqlite.drop_table"]

    def test_snippet_is_trimmed_single_line(self) -> None:
        ddl = """
        ALTER TABLE items
            ADD COLUMN
                new_col TEXT NOT NULL;
        """
        hits = scan(ddl, authoritative_db_kind=KIND)
        assert len(hits) == 1
        assert "\n" not in hits[0].snippet


class TestCommentHandling:
    def test_line_comment_does_not_trigger_hit(self) -> None:
        hits = scan(
            "-- DROP TABLE items;\nSELECT 1;",
            authoritative_db_kind=KIND,
        )
        assert hits == []

    def test_block_comment_does_not_trigger_hit(self) -> None:
        hits = scan(
            "/* DROP TABLE items; */ SELECT 1;",
            authoritative_db_kind=KIND,
        )
        assert hits == []


class TestMultipleStatementsOneDdl:
    def test_multiple_hits_aggregated(self) -> None:
        # Scanner is single source of truth; callers receive every
        # hit from a multi-statement migration module.
        ddl = """
        DROP TABLE old_items;
        ALTER TABLE items ADD COLUMN new_col TEXT NOT NULL;
        CREATE UNIQUE INDEX idx_items_title ON items(title);
        """
        hits = scan(ddl, authoritative_db_kind=KIND)
        ids = _ids(hits)
        assert "sqlite.drop_table" in ids
        assert "sqlite.add_column_not_null_no_default" in ids
        assert "sqlite.create_unique_index" in ids

    def test_safe_ddl_returns_no_hits(self) -> None:
        ddl = """
        ALTER TABLE items ADD COLUMN new_col TEXT;
        CREATE INDEX idx_items_new_col ON items(new_col);
        UPDATE items SET new_col = '' WHERE new_col IS NULL;
        """
        hits = scan(ddl, authoritative_db_kind=KIND)
        assert hits == []


class TestHasBannedPatternShortcut:
    def test_true_when_pattern_matches(self) -> None:
        assert has_banned_pattern("DROP TABLE items;", authoritative_db_kind=KIND)

    def test_false_when_safe(self) -> None:
        assert not has_banned_pattern(
            "ALTER TABLE items ADD COLUMN x TEXT;",
            authoritative_db_kind=KIND,
        )
