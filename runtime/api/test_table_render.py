"""Tests for yoke_core.domain.table_render module.

Covers: pipe_delimited() and markdown_table() output formats.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.table_render import markdown_table, pipe_delimited


class TestPipeDelimited:
    """Test pipe-delimited output format."""

    def test_basic_output(self) -> None:
        rows = [
            {"id": 1, "name": "alpha", "val": 10},
            {"id": 2, "name": "beta", "val": 20},
        ]
        result = pipe_delimited(rows, ["id", "name", "val"])
        assert result == "1|alpha|10\n2|beta|20"

    def test_single_column(self) -> None:
        rows = [{"name": "x"}, {"name": "y"}]
        result = pipe_delimited(rows, ["name"])
        assert result == "x\ny"

    def test_empty_rows(self) -> None:
        result = pipe_delimited([], ["id", "name"])
        assert result == ""

    def test_missing_key_becomes_empty(self) -> None:
        rows = [{"id": 1}]  # 'name' key missing
        result = pipe_delimited(rows, ["id", "name"])
        assert result == "1|"

    def test_none_value_becomes_empty(self) -> None:
        rows = [{"id": 1, "name": None}]
        result = pipe_delimited(rows, ["id", "name"])
        assert result == "1|"

    def test_name_indexed_row_object(self) -> None:
        """Works with name-indexed DB row objects, not just plain dicts."""
        from yoke_core.domain.db_backend import PostgresRow

        rows = [PostgresRow(("id", "name"), (1, "foo"))]
        result = pipe_delimited(rows, ["id", "name"])
        assert result == "1|foo"


class TestMarkdownTable:
    """Test Markdown table output format."""

    def test_basic_table(self) -> None:
        rows = [
            {"id": 1, "name": "alpha"},
            {"id": 2, "name": "beta"},
        ]
        result = markdown_table(rows, ["id", "name"])
        lines = result.split("\n")
        assert len(lines) == 4  # header + separator + 2 data rows
        assert lines[0].startswith("| id")
        assert lines[1].startswith("| --")
        assert "alpha" in lines[2]
        assert "beta" in lines[3]

    def test_custom_headers(self) -> None:
        rows = [{"id": 1, "name": "a"}]
        result = markdown_table(
            rows, ["id", "name"], headers=["ID", "Name"]
        )
        lines = result.split("\n")
        assert "ID" in lines[0]
        assert "Name" in lines[0]

    def test_empty_rows_produces_header_only(self) -> None:
        result = markdown_table([], ["id", "name"])
        lines = result.split("\n")
        assert len(lines) == 2  # header + separator, no data rows

    def test_column_widths_adapt(self) -> None:
        rows = [{"name": "a-very-long-name"}]
        result = markdown_table(rows, ["name"])
        lines = result.split("\n")
        # Separator dashes should be at least as wide as the data
        sep_width = len(lines[1].strip("| ").strip())
        assert sep_width >= len("a-very-long-name")

    def test_headers_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="headers length"):
            markdown_table([], ["a", "b"], headers=["Only One"])

    def test_minimum_separator_width(self) -> None:
        """Separator dashes are at least 3 chars wide."""
        rows = [{"x": "1"}]
        result = markdown_table(rows, ["x"])
        lines = result.split("\n")
        # Extract the separator cell content between pipes
        sep_content = lines[1].split("|")[1].strip()
        assert len(sep_content) >= 3
