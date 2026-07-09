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
from yoke_core.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
    SEED_UPDATED_AT,
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


class TestReads:
    def test_list_docs_orders_defaults_first_then_alpha(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            docs = sd.list_docs(conn, PROJECT_A)
        finally:
            conn.close()
        assert [d["slug"] for d in docs] == [
            "MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "PAD", "WISPS",
        ]
        for doc in docs:
            assert doc["bytes"] == len(SEED_CONTENT[doc["slug"]].encode("utf-8"))
            assert doc["updated_at"] == SEED_UPDATED_AT

    def test_list_docs_resolves_updated_by_label(self, tmp_db: str) -> None:
        from yoke_core.domain.actors import resolve_actor_by_label

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            editor = resolve_actor_by_label(conn, "ben")  # canonical seed
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
                conn, PROJECT_B, "MISSION", "# B mission\n\nproject B body.\n",
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
                conn, PROJECT_B, "MISSION",
                SEED_CONTENT["MISSION"] + "B-only addition.\n",
                None, base_updated_at=SEED_UPDATED_AT,
            )
            a_doc = sd.get_doc(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert a_doc["content"] == SEED_CONTENT["MISSION"]
        assert a_doc["updated_at"] == SEED_UPDATED_AT


class TestReplaceGuards:
    def test_empty_content_refused(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.EmptyStrategyDocError):
                sd.replace_doc(conn, PROJECT_A, "MISSION", "   \n", None,
                               base_updated_at=SEED_UPDATED_AT)
        finally:
            conn.close()

    def test_invalid_slug_refused(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.UnknownStrategyDocError):
                sd.replace_doc(conn, PROJECT_A, "bad/slug", "# body\n", None,
                               base_updated_at=SEED_UPDATED_AT)
        finally:
            conn.close()

    def test_shrink_refused_without_force(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.StrategyDocShrinkError):
                sd.replace_doc(conn, PROJECT_A, "MISSION", "# tiny\n", None,
                               base_updated_at=SEED_UPDATED_AT)
            # Guard refused: stored content unchanged.
            assert (
                sd.get_doc(conn, PROJECT_A, "MISSION")["content"]
                == SEED_CONTENT["MISSION"]
            )
        finally:
            conn.close()

    def test_shrink_allowed_with_force(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = sd.replace_doc(
                conn, PROJECT_A, "MISSION", "# tiny\n", 7,
                base_updated_at=SEED_UPDATED_AT, force=True,
            )
            assert result["new_bytes"] == len(b"# tiny\n")
            assert sd.get_doc(conn, PROJECT_A, "MISSION")["content"] == "# tiny\n"
        finally:
            conn.close()


class TestReplaceWrite:
    def test_replace_updates_row_and_reports_bytes(self, tmp_db: str) -> None:
        new_content = SEED_CONTENT["VISION"] + "\nAppended paragraph.\n"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = sd.replace_doc(
                conn, PROJECT_A, "VISION", new_content, 42,
                base_updated_at=SEED_UPDATED_AT,
            )
            assert result["slug"] == "VISION"
            assert result["old_bytes"] == len(
                SEED_CONTENT["VISION"].encode("utf-8")
            )
            assert result["new_bytes"] == len(new_content.encode("utf-8"))

            row = fetch_row(conn, PROJECT_A, "VISION")
            assert str(row["content"]) == new_content
            assert str(row["updated_at"]) == result["updated_at"]
            assert int(row["updated_by_actor_id"]) == 42
        finally:
            conn.close()

    def test_replace_identical_content_is_noop(self, tmp_db: str) -> None:
        """Re-replacing the exact stored content must NOT advance the row.

        A no-op write that still minted a fresh updated_at would churn the
        gitignored .yoke/strategy/ render header (new CAS timestamp) with no
        real edit — the dirty-strategy-file recurrence. The gate preserves
        updated_at + updated_by and reports unchanged=True.
        """
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            before = fetch_row(conn, PROJECT_A, "VISION")
            result = sd.replace_doc(
                conn, PROJECT_A, "VISION", SEED_CONTENT["VISION"], 99,
                base_updated_at=SEED_UPDATED_AT,
            )
            assert result["unchanged"] is True
            assert result["updated_at"] == str(before["updated_at"])
            after = fetch_row(conn, PROJECT_A, "VISION")
            # Row untouched: timestamp preserved, actor 99 NOT recorded.
            assert str(after["updated_at"]) == str(before["updated_at"])
            assert after["updated_by_actor_id"] == before["updated_by_actor_id"]
            assert str(after["content"]) == SEED_CONTENT["VISION"]
        finally:
            conn.close()

    def test_replace_missing_row_raises(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, skip=("WISPS",))
            with pytest.raises(sd.StrategyDocMissingError):
                sd.replace_doc(conn, PROJECT_A, "WISPS",
                               "# body that is long enough\n",
                               None, base_updated_at=SEED_UPDATED_AT)
        finally:
            conn.close()

    def test_replace_stale_base_conflicts_and_preserves_row(
        self, tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.replace_doc(
                conn, PROJECT_A, "VISION",
                SEED_CONTENT["VISION"] + "First writer.\n",
                1, base_updated_at=SEED_UPDATED_AT,
            )
            current = sd.get_doc(conn, PROJECT_A, "VISION")
            with pytest.raises(sd.StrategyDocConflictError) as exc:
                sd.replace_doc(
                    conn, PROJECT_A, "VISION",
                    SEED_CONTENT["VISION"] + "Second writer, stale base.\n",
                    2, base_updated_at=SEED_UPDATED_AT,
                )
            # Conflict teaching names the re-read recovery; the first
            # writer's content survives untouched.
            assert "doc get VISION" in str(exc.value)
            assert (
                sd.get_doc(conn, PROJECT_A, "VISION")["content"]
                == current["content"]
            )
        finally:
            conn.close()

    def test_replace_stale_base_identical_content_conflicts(
        self, tmp_db: str,
    ) -> None:
        """Stale base + content equal to the live row still CAS-conflicts.

        The no-op short-circuit (identical content -> unchanged) only fires
        when the caller's base is ALSO current. A second writer whose base is
        stale but whose content happens to equal the now-current row authored
        against a version they never re-read — strict CAS refuses it rather
        than swallowing it as a no-op. Sibling of the stale-base test above,
        which uses *different* content; this case (identical content) is the
        one the no-op gate masked until base-freshness was made load-bearing.
        """
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            landed = SEED_CONTENT["VISION"] + "First writer.\n"
            sd.replace_doc(
                conn, PROJECT_A, "VISION", landed, 1,
                base_updated_at=SEED_UPDATED_AT,
            )
            current = sd.get_doc(conn, PROJECT_A, "VISION")
            assert current["updated_at"] != SEED_UPDATED_AT  # row advanced
            # Same content as the live row, but the now-stale seed base.
            with pytest.raises(sd.StrategyDocConflictError):
                sd.replace_doc(
                    conn, PROJECT_A, "VISION", landed, 2,
                    base_updated_at=SEED_UPDATED_AT,
                )
            # Conflict, not a silent no-op: the row keeps the first writer's
            # identity (updated_at + actor), never re-stamped by the stale write.
            after = sd.get_doc(conn, PROJECT_A, "VISION")
            assert after["content"] == landed
            assert after["updated_at"] == current["updated_at"]
            assert after["updated_by_actor_id"] == 1
        finally:
            conn.close()

    def test_replace_requires_base_updated_at(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(ValueError, match="base_updated_at"):
                sd.replace_doc(
                    conn, PROJECT_A, "VISION", SEED_CONTENT["VISION"] + "x\n",
                    None, base_updated_at="  ",
                )
        finally:
            conn.close()
