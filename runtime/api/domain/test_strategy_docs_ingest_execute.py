"""Tests for ``strategy_docs_ingest.execute_ingest`` — the CAS write path.

Covers written/unchanged/conflict outcomes, actor stamping, mixed-batch
behavior past a conflict, and cross-project isolation. Plan validation
and dry-run preview live in ``test_strategy_docs_ingest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_ingest as ing
from yoke_core.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    bump_db_row,
    edit_body,
    fetch_row,
    insert_doc,
    seed_docs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


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


class TestExecute:
    def test_written_advances_row_with_actor(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        new_body = SEED_CONTENT["VISION"] + "Sharper vision.\n"
        edit_body(checkout, "VISION", new_body)
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(checkout, ["VISION"]),
            )
            (result,) = ing.execute_ingest(
                conn, plans, project_id=PROJECT_A, actor_id=42,
            )
            row = fetch_row(conn, PROJECT_A, "VISION")
        finally:
            conn.close()
        assert result["status"] == "written"
        assert result["updated_at"] != SEED_UPDATED_AT
        assert str(row["content"]) == new_body
        assert str(row["updated_at"]) == result["updated_at"]
        assert int(row["updated_by_actor_id"]) == 42

    def test_unchanged_docs_noop(self, tmp_db: str, checkout: Path) -> None:
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(
                    checkout, sd.project_doc_slugs(conn, PROJECT_A),
                ),
            )
            results = ing.execute_ingest(
                conn, plans, project_id=PROJECT_A, actor_id=None,
            )
            row = fetch_row(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert all(r["status"] == "unchanged" for r in results)
        assert str(row["updated_at"]) == SEED_UPDATED_AT

    def test_ingest_never_touches_other_project_same_slug(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(checkout, "PAD", SEED_CONTENT["PAD"] + "A-side edit.\n")
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(checkout, ["PAD"]),
            )
            (result,) = ing.execute_ingest(
                conn, plans, project_id=PROJECT_A, actor_id=None,
            )
            b_row = fetch_row(conn, PROJECT_B, "PAD")
        finally:
            conn.close()
        assert result["status"] == "written"
        # Project B's same-slug row is untouched by a project-A ingest.
        assert str(b_row["content"]) == "# B PAD\n\nproject B body.\n"
        assert str(b_row["updated_at"]) == SEED_UPDATED_AT

    def test_cas_conflict_preserves_newer_db_content(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Local edit.\n")
        bump_db_row(tmp_db, "PAD")
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(checkout, ["PAD"]),
            )
            (result,) = ing.execute_ingest(
                conn, plans, project_id=PROJECT_A, actor_id=7,
            )
            row = fetch_row(conn, PROJECT_A, "PAD")
        finally:
            conn.close()
        assert result["status"] == "conflict"
        assert result["base_updated_at"] == SEED_UPDATED_AT
        # The newer DB write survives untouched.
        assert str(row["updated_at"]) == "2026-06-11T11:11:11Z"
        assert "DB moved on." in str(row["content"])

    def test_mixed_batch_writes_clean_docs_past_a_conflict(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_body(checkout, "MISSION", SEED_CONTENT["MISSION"] + "Edit A.\n")
        edit_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit B.\n")
        bump_db_row(tmp_db, "PAD")
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(
                    checkout, ["MISSION", "PAD", "VISION"],
                ),
            )
            results = {
                r["slug"]: r["status"]
                for r in ing.execute_ingest(
                    conn, plans, project_id=PROJECT_A, actor_id=None,
                )
            }
        finally:
            conn.close()
        assert results == {
            "MISSION": "written", "PAD": "conflict", "VISION": "unchanged",
        }
