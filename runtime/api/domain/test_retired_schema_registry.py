"""Tests for the retired-schema surface registry loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import retired_schema_registry as rsr


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


def _write_registry(root: Path, body: str) -> None:
    target = root / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


class TestLoadRegistry:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        # No file staged — loader returns empty list.
        assert rsr.load_registry(tmp_path) == []

    def test_empty_surfaces_list(self, tmp_path: Path) -> None:
        _write_registry(tmp_path, "surfaces: []\n")
        assert rsr.load_registry(tmp_path, force_reload=True) == []

    def test_parses_column_entry(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo_cutover\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: legacy_col\n"
            "    decision_record: docs/archive/decisions/demo_cutover.md\n",
        )
        records = rsr.load_registry(tmp_path, force_reload=True)
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, rsr.RetiredSurface)
        assert rec.module == "demo_cutover"
        assert rec.project == "yoke"
        assert rec.model == "primary"
        assert rec.table == "projects"
        assert rec.column == "legacy_col"
        assert rec.decision_record == (
            "docs/archive/decisions/demo_cutover.md"
        )

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo\n"
            "    project: yoke\n"
            "    model: primary\n",  # table missing
        )
        with pytest.raises(rsr.RetiredSchemaRegistryError):
            rsr.load_registry(tmp_path, force_reload=True)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        _write_registry(tmp_path, ": not valid ::\n")
        with pytest.raises(rsr.RetiredSchemaRegistryError):
            rsr.load_registry(tmp_path, force_reload=True)

    def test_cache_hits_on_repeated_calls(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: one\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: t1\n"
            "    column: c1\n",
        )
        first = rsr.load_registry(tmp_path)
        # Mutate file; without force_reload the cached list is returned.
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: two\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: t2\n"
            "    column: c2\n",
        )
        second = rsr.load_registry(tmp_path)
        assert [r.module for r in first] == [r.module for r in second] == ["one"]
        reloaded = rsr.load_registry(tmp_path, force_reload=True)
        assert [r.module for r in reloaded] == ["two"]


class TestQueryHelpers:
    @pytest.fixture
    def registry_root(self, tmp_path: Path) -> Path:
        # Synthetic retirement names so the residue grep asserted by
        # AC-11 stays clean outside the registry file itself.
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo_cutover\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: legacy_alpha_col\n"
            "  - module: demo_sibling_cutover\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: widgets\n"
            "    column: legacy_beta_col\n"
            "  - module: other_project_cut\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: widgets\n"
            "    column: legacy_gamma_col\n",
        )
        return tmp_path

    def test_is_retired_column_matches(self, registry_root: Path) -> None:
        assert rsr.is_retired_column(
            "yoke", "projects", "legacy_alpha_col",
            repo_root=registry_root,
        )
        assert not rsr.is_retired_column(
            "yoke", "projects", "some_other_col",
            repo_root=registry_root,
        )
        # Column exists but on a different project → no match.
        assert not rsr.is_retired_column(
            "yoke", "widgets", "legacy_gamma_col",
            repo_root=registry_root,
        )

    def test_lookup_module(self, registry_root: Path) -> None:
        assert rsr.lookup_module(
            "yoke", "projects", "legacy_alpha_col",
            repo_root=registry_root,
        ) == "demo_cutover"
        assert rsr.lookup_module(
            "yoke", "projects", "unknown", repo_root=registry_root,
        ) is None

    def test_list_retired_columns_for_table(
        self, registry_root: Path
    ) -> None:
        out = rsr.list_retired_columns_for_table(
            "yoke", "projects", repo_root=registry_root,
        )
        assert [r.column for r in out] == ["legacy_alpha_col"]

    def test_list_all_retired_columns_across_projects(
        self, registry_root: Path
    ) -> None:
        out = rsr.list_all_retired_columns(repo_root=registry_root)
        assert len(out) == 3
        projects = {r.project for r in out}
        assert projects == {"yoke", "buzz"}


class TestGuardAddColumn:
    def test_allows_non_retired_columns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_registry(tmp_path, "surfaces: []\n")
        assert rsr.guard_add_column(
            "yoke", "projects", "new_col",
            caller="test", repo_root=tmp_path,
        ) is True

    def test_blocks_retired_columns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: retired_col\n",
        )
        # The event emission path is best-effort and tolerates missing
        # event infrastructure; we only assert the guard return value
        # here because emit_event plumbing requires a populated events
        # table which this unit test does not stage.
        called = {"emit": 0}

        def fake_emit(**kwargs):  # noqa: ANN003
            called["emit"] += 1

        monkeypatch.setattr(rsr, "_emit_resurrection_warn", fake_emit)
        allowed = rsr.guard_add_column(
            "yoke", "projects", "retired_col",
            caller="yoke_core.domain.projects_restart",
            repo_root=tmp_path,
        )
        assert allowed is False
        assert called["emit"] == 1

    def test_registry_error_degrades_to_allow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_a, **_k):
            raise rsr.RetiredSchemaRegistryError("boom")

        monkeypatch.setattr(rsr, "lookup_module", _raise)
        # Malformed registry must not hard-fail init/bootstrap.
        assert rsr.guard_add_column(
            "yoke", "projects", "any_col",
            caller="test", repo_root=tmp_path,
        ) is True
