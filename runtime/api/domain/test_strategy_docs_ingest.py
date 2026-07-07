"""Tests for ``strategy_docs_ingest`` plan validation + dry-run preview.

The compare-and-swap execute path (including cross-project isolation)
lives in ``test_strategy_docs_ingest_execute.py``; shared fixtures in
``strategy_docs_test_helpers``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_ingest as ing
from yoke_core.domain.strategy_docs_header import StrategyHeaderError
from yoke_core.domain.strategy_docs_paths import strategy_view_path
from yoke_core.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
    SEED_SLUGS,
    SEED_UPDATED_AT,
    bump_db_row,
    edit_body,
    insert_doc,
    seed_docs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _plan(conn, checkout: Path, slugs) -> list:
    """read_ingest_files + plan_ingest — the split the CLI composes."""
    return ing.plan_ingest(
        conn, project_id=PROJECT_A,
        files=ing.read_ingest_files(checkout, slugs),
    )


@pytest.fixture
def checkout(tmp_db: str, tmp_path: Path) -> Path:
    """Seeded DB (project A corpus + a project B doc) + rendered checkout."""
    conn = connect_test_db(tmp_db)
    try:
        seed_docs(conn, PROJECT_A)
        insert_doc(conn, PROJECT_B, "PAD", "# B PAD\n\nproject B body.\n")
        conn.commit()
    finally:
        conn.close()
    root = tmp_path / "checkout"
    sd.render_docs(target_root=root, project_id=PROJECT_A)
    return root


class TestPlanValidation:
    def test_missing_file_refused_naming_path(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        strategy_view_path(checkout, "PAD").unlink()
        conn = connect_test_db(tmp_db)
        try:
            with pytest.raises(ing.StrategyIngestFileMissingError) as exc:
                ing.read_ingest_files(checkout, ["PAD"])
        finally:
            conn.close()
        assert "PAD.md" in str(exc.value)

    def test_headerless_file_refused_naming_file(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        path = strategy_view_path(checkout, "PAD")
        path.write_text("# PAD\n\nno header here\n", encoding="utf-8")
        conn = connect_test_db(tmp_db)
        try:
            with pytest.raises(StrategyHeaderError) as exc:
                _plan(conn, checkout, ["PAD"])
        finally:
            conn.close()
        assert exc.value.kind == "missing"
        assert "PAD.md" in str(exc.value)
        assert "yoke strategy render" in str(exc.value)

    def test_header_slug_mismatch_refused(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        mission = strategy_view_path(checkout, "MISSION").read_text(
            encoding="utf-8"
        )
        strategy_view_path(checkout, "PAD").write_text(mission, encoding="utf-8")
        conn = connect_test_db(tmp_db)
        try:
            with pytest.raises(StrategyHeaderError) as exc:
                _plan(conn, checkout, ["PAD"])
        finally:
            conn.close()
        assert exc.value.kind == "mangled"
        assert "MISSION" in str(exc.value)

    def test_invalid_slug_shape_refused(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            with pytest.raises(sd.UnknownStrategyDocError):
                ing.plan_ingest(
                    conn, project_id=PROJECT_A,
                    files=[{"slug": "../escape", "path": "x.md", "text": "y\n"}],
                )
        finally:
            conn.close()

    def test_missing_db_row_refused(self, tmp_db: str, checkout: Path) -> None:
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"DELETE FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_A, "WISPS"),
            )
            conn.commit()
            with pytest.raises(sd.StrategyDocMissingError):
                _plan(conn, checkout, ["WISPS"])
        finally:
            conn.close()

    def test_default_slugs_are_project_corpus(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            # The CLI resolves the no-args default from the project corpus
            # (strategy.doc.list); compose the same default here.
            plans = _plan(conn, checkout, sd.project_doc_slugs(conn, PROJECT_A))
        finally:
            conn.close()
        # Project B's PAD row is invisible to a project-A ingest plan.
        assert sorted(p.slug for p in plans) == sorted(SEED_SLUGS)

    def test_changed_to_empty_body_refused(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(checkout, "PAD", "   \n")
        conn = connect_test_db(tmp_db)
        try:
            with pytest.raises(sd.EmptyStrategyDocError) as exc:
                _plan(conn, checkout, ["PAD"])
        finally:
            conn.close()
        assert "PAD" in str(exc.value)


class TestDryRun:
    def test_changed_unchanged_and_line_delta(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(
            checkout, "PAD",
            SEED_CONTENT["PAD"] + "New idea line.\nAnother.\n",
        )
        conn = connect_test_db(tmp_db)
        try:
            plans = _plan(conn, checkout, sd.project_doc_slugs(conn, PROJECT_A))
        finally:
            conn.close()
        report = {d["slug"]: d for d in ing.dry_run_report(plans)}
        assert report["PAD"]["status"] == "changed"
        assert report["PAD"]["line_delta"] == 2
        for slug in SEED_SLUGS:
            if slug != "PAD":
                assert report[slug]["status"] == "unchanged"

    def test_stale_base_previews_as_conflict(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Local edit.\n")
        bump_db_row(tmp_db, "PAD")
        conn = connect_test_db(tmp_db)
        try:
            plans = _plan(conn, checkout, ["PAD"])
        finally:
            conn.close()
        (doc,) = ing.dry_run_report(plans)
        assert doc["status"] == "conflict"
        assert doc["base_updated_at"] == SEED_UPDATED_AT
        assert doc["db_updated_at"] == "2026-06-11T11:11:11Z"

    def test_conflict_teaching_names_recovery_steps(self) -> None:
        teaching = ing.conflict_teaching(["PAD", "WISPS"], Path("/repo"))
        assert "'PAD'" in teaching and "'WISPS'" in teaching
        assert "yoke strategy render --target-root /repo" in teaching
        assert "git diff" in teaching
        assert "yoke strategy ingest PAD WISPS" in teaching
