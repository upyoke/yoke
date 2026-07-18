"""Tests for table-level retired-schema registry helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import retired_schema_registry as rsr
from yoke_core.domain import retired_schema_table_registry as tables


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


def _write_registry(root: Path, body: str) -> None:
    target = root / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


class TestTableLevelParsing:
    def test_parses_table_level_entry(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: dropped_table_cutover\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: legacy_table\n"
            "    decision_record: docs/archive/decisions/dropped_table_cutover.md\n",
        )
        records = rsr.load_registry(tmp_path, force_reload=True)
        assert len(records) == 1
        rec = records[0]
        assert rec.table == "legacy_table"
        assert rec.column is None
        assert rec.module == "dropped_table_cutover"

    def test_parses_mixed_table_and_column_entries(
        self, tmp_path: Path
    ) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_t1\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: t1\n"
            "  - module: drop_t2_col\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: t2\n"
            "    column: legacy_col\n",
        )
        records = rsr.load_registry(tmp_path, force_reload=True)
        by_module = {r.module: r for r in records}
        assert by_module["drop_t1"].column is None
        assert by_module["drop_t2_col"].column == "legacy_col"

    def test_empty_string_column_rejected(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: m\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: t\n"
            "    column: ''\n",
        )
        with pytest.raises(rsr.RetiredSchemaRegistryError):
            rsr.load_registry(tmp_path, force_reload=True)


class TestTableLevelHelpers:
    @pytest.fixture
    def registry_root(self, tmp_path: Path) -> Path:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_legacy_table\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: legacy_table\n"
            "  - module: drop_other_col\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: other_table\n"
            "    column: deprecated_col\n"
            "  - module: drop_table_in_externalwebapp\n"
            "    project: externalwebapp\n"
            "    model: primary\n"
            "    table: legacy_table\n",
        )
        return tmp_path

    def test_is_retired_table_matches(self, registry_root: Path) -> None:
        assert tables.is_retired_table(
            "yoke", "legacy_table", repo_root=registry_root,
        )

    def test_is_retired_table_project_scoped(
        self, registry_root: Path
    ) -> None:
        assert not tables.is_retired_table(
            "other_project", "legacy_table", repo_root=registry_root,
        )

    def test_is_retired_table_does_not_match_column_entry(
        self, registry_root: Path
    ) -> None:
        assert not tables.is_retired_table(
            "yoke", "other_table", repo_root=registry_root,
        )

    def test_lookup_module_for_table(self, registry_root: Path) -> None:
        assert tables.lookup_module_for_table(
            "yoke", "legacy_table", repo_root=registry_root,
        ) == "drop_legacy_table"
        assert tables.lookup_module_for_table(
            "yoke", "other_table", repo_root=registry_root,
        ) is None

    def test_list_all_retired_tables(self, registry_root: Path) -> None:
        out = tables.list_all_retired_tables(repo_root=registry_root)
        assert {r.module for r in out} == {
            "drop_legacy_table",
            "drop_table_in_externalwebapp",
        }
        assert all(r.column is None for r in out)

    def test_table_and_column_helpers_do_not_cross_match(
        self, registry_root: Path
    ) -> None:
        assert not rsr.is_retired_column(
            "yoke", "legacy_table", "any_col",
            repo_root=registry_root,
        )
        assert not tables.is_retired_table(
            "yoke", "other_table", repo_root=registry_root,
        )
