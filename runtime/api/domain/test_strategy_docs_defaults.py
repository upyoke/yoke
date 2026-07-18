"""Tests for strategy-doc cold-start defaults and the path resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_defaults as defaults
from yoke_core.domain import strategy_docs_paths as paths
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestSeedDefaults:
    def test_seed_mints_default_rows_parameterized_by_name(
        self, tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            report = defaults.seed_default_docs(conn, 2, "ExternalWebapp")
            docs = sd.list_docs(conn, 2)
            mission = sd.get_doc(conn, 2, "MISSION")
        finally:
            conn.close()
        assert report["already_seeded"] is False
        assert report["seeded"] == list(defaults.DEFAULT_STRATEGY_DOC_SLUGS)
        assert [d["slug"] for d in docs] == list(defaults.DEFAULT_STRATEGY_DOC_SLUGS)
        assert "ExternalWebapp" in mission["content"]
        assert "TODO" in mission["content"]

    def test_seed_is_idempotent(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            defaults.seed_default_docs(conn, 2, "ExternalWebapp")
            second = defaults.seed_default_docs(conn, 2, "ExternalWebapp")
            count = conn.execute(
                f"SELECT COUNT(*) FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s",
                (2,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert second["already_seeded"] is True
        assert second["seeded"] == []
        assert int(count) == len(defaults.DEFAULT_STRATEGY_DOC_SLUGS)

    def test_seed_noops_on_any_existing_row(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
                "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
                (2, "MASTER-PLAN", "# existing plan\n", sd.next_updated_at()),
            )
            conn.commit()
            report = defaults.seed_default_docs(conn, 2, "ExternalWebapp")
            slugs = sd.project_doc_slugs(conn, 2)
        finally:
            conn.close()
        # An established corpus (even partial vs the default canon) is
        # never extended by cold-start seeding.
        assert report["already_seeded"] is True
        assert slugs == ["MASTER-PLAN"]

    def test_seed_scopes_to_one_project(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            defaults.seed_default_docs(conn, 2, "ExternalWebapp")
            slugs_other = sd.project_doc_slugs(conn, 1)
        finally:
            conn.close()
        assert slugs_other == []

    def test_placeholder_unknown_slug_raises(self) -> None:
        with pytest.raises(ValueError, match="default canon"):
            defaults.placeholder_content("PAD", "ExternalWebapp")


class TestPathResolver:
    def test_rel_path_and_dir(self, tmp_path: Path) -> None:
        assert paths.strategy_view_rel_path("MISSION") == (
            ".yoke/strategy/MISSION.md"
        )
        assert paths.strategy_dir(tmp_path) == tmp_path / ".yoke" / "strategy"
        assert paths.strategy_view_path(tmp_path, "PAD") == (
            tmp_path / ".yoke" / "strategy" / "PAD.md"
        )

    def test_slug_from_view_path(self) -> None:
        assert paths.slug_from_view_path(".yoke/strategy/MISSION.md") == "MISSION"
        assert paths.slug_from_view_path(".yoke/strategy/PAD.md") == "PAD"
        assert paths.slug_from_view_path("strategy/MISSION.md") is None
        assert paths.slug_from_view_path(".yoke/strategy/nested/X.md") is None
        assert paths.slug_from_view_path(".yoke/strategy/notes.txt") is None
        assert paths.slug_from_view_path(".yoke/strategy/.md") is None

    def test_is_strategy_view_path(self) -> None:
        assert paths.is_strategy_view_path(".yoke/strategy/WISPS.md")
        assert not paths.is_strategy_view_path(".yoke/BOARD.md")
        assert not paths.is_strategy_view_path("docs/atlas.md")
