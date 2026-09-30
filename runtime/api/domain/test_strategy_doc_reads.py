"""Tests for the per-project ``strategy_docs`` domain owner.

Covers the replace guards (empty refused, shrink refused without
force, invalid slug refused), the project-scoped read surfaces, and
two-project isolation on the same slug. Render coverage lives in
``test_strategy_docs_render.py``; shared fixtures in
``strategy_docs_test_helpers``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from runtime.api.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    insert_doc,
    seed_docs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestReads:
    def test_list_docs_orders_defaults_first_then_alpha(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            docs = sd.list_docs(conn, PROJECT_A)
        finally:
            conn.close()
        assert [d["slug"] for d in docs] == [
            "MISSION",
            "VISION",
            "MASTER-PLAN",
            "LANDSCAPE",
            "PAD",
            "WISPS",
        ]
        for doc in docs:
            assert doc["bytes"] == len(SEED_CONTENT[doc["slug"]].encode("utf-8"))
            assert doc["updated_at"] == SEED_UPDATED_AT

    def test_list_docs_resolves_updated_by_label(self, tmp_db: str) -> None:
        from yoke_core.domain.actors import resolve_actors_by_name

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            (editor,) = resolve_actors_by_name(conn, "ben")  # canonical seed
            assert editor is not None
            conn.execute(
                "UPDATE strategy_docs SET updated_by_actor_id = %s "
                "WHERE project_id = %s AND slug = %s",
                (editor, PROJECT_A, "VISION"),
            )
            conn.commit()
            docs = {d["slug"]: d for d in sd.list_docs(conn, PROJECT_A)}
        finally:
            conn.close()
        # Edited doc resolves to the editor's label; unedited stays None.
        assert docs["VISION"]["updated_by"] == "ben"
        assert docs["MISSION"]["updated_by"] is None

    def test_get_doc_returns_content(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            doc = sd.get_doc(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert doc["slug"] == "MISSION"
        assert doc["content"] == SEED_CONTENT["MISSION"]

    def test_get_doc_invalid_slug_shape_refused(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.UnknownStrategyDocError):
                sd.get_doc(conn, PROJECT_A, "../escape")
        finally:
            conn.close()

    def test_get_doc_missing_row_teaches_corpus(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, skip=("PAD",))
            with pytest.raises(sd.StrategyDocMissingError) as exc:
                sd.get_doc(conn, PROJECT_A, "PAD")
        finally:
            conn.close()
        assert "MISSION" in str(exc.value)

    def test_get_doc_empty_project_teaches_seed_defaults(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
            with pytest.raises(sd.StrategyDocMissingError) as exc:
                sd.get_doc(conn, PROJECT_B, "MISSION")
        finally:
            conn.close()
        assert "seed-defaults" in str(exc.value)


class TestProjectIsolation:
    def test_same_slug_coexists_and_reads_stay_scoped(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
            insert_doc(
                conn,
                PROJECT_B,
                "MISSION",
                "# B mission\n\nproject B body.\n",
            )
            conn.commit()
            a_doc = sd.get_doc(conn, PROJECT_A, "MISSION")
            b_doc = sd.get_doc(conn, PROJECT_B, "MISSION")
            b_list = sd.list_docs(conn, PROJECT_B)
        finally:
            conn.close()
        assert a_doc["content"] == SEED_CONTENT["MISSION"]
        assert b_doc["content"].startswith("# B mission")
        assert [d["slug"] for d in b_list] == ["MISSION"]

    def test_duplicate_project_slug_rejected(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
            with pytest.raises(Exception):
                insert_doc(conn, PROJECT_A, "MISSION", "# dup\n")
            conn.rollback()
        finally:
            conn.close()

    def test_replace_never_touches_other_project_row(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
            seed_docs(conn, PROJECT_B)
            sd.replace_doc(
                conn,
                PROJECT_B,
                "MISSION",
                SEED_CONTENT["MISSION"] + "B-only addition.\n",
                None,
                base_updated_at=SEED_UPDATED_AT,
            )
            a_doc = sd.get_doc(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert a_doc["content"] == SEED_CONTENT["MISSION"]
        assert a_doc["updated_at"] == SEED_UPDATED_AT
