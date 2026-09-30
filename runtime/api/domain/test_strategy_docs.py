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
    card_document,
    PROJECT_A,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    fetch_row,
    seed_docs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestReplaceGuards:
    def test_empty_content_refused(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.EmptyStrategyDocError):
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "MISSION",
                    "   \n",
                    None,
                    base_updated_at=SEED_UPDATED_AT,
                )
        finally:
            conn.close()

    def test_invalid_slug_refused(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.UnknownStrategyDocError):
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "bad/slug",
                    "# body\n",
                    None,
                    base_updated_at=SEED_UPDATED_AT,
                )
        finally:
            conn.close()

    def test_shrink_refused_without_force(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            conn.execute(
                "UPDATE strategy_docs SET content = content || %s WHERE project_id = %s AND slug = %s",
                ("large body\n" * 100, PROJECT_A, "MISSION"),
            )
            conn.commit()
            with pytest.raises(sd.StrategyDocShrinkError):
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "MISSION",
                    card_document("# tiny\n"),
                    None,
                    base_updated_at=SEED_UPDATED_AT,
                )
            # Guard refused: stored content unchanged.
            assert (
                sd.get_doc(conn, PROJECT_A, "MISSION")["content"]
                == SEED_CONTENT["MISSION"] + "large body\n" * 100
            )
        finally:
            conn.close()

    def test_shrink_allowed_with_force(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = sd.replace_doc(
                conn,
                PROJECT_A,
                "MISSION",
                card_document("# tiny\n"),
                7,
                base_updated_at=SEED_UPDATED_AT,
                force=True,
            )
            assert result["new_bytes"] == len(card_document("# tiny\n").encode())
            assert sd.get_doc(conn, PROJECT_A, "MISSION")["content"] == card_document(
                "# tiny\n"
            )
        finally:
            conn.close()


class TestReplaceWrite:
    def test_replace_updates_row_and_reports_bytes(self, tmp_db: str) -> None:
        new_content = SEED_CONTENT["VISION"] + "\nAppended paragraph.\n"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = sd.replace_doc(
                conn,
                PROJECT_A,
                "VISION",
                new_content,
                42,
                base_updated_at=SEED_UPDATED_AT,
            )
            assert result["slug"] == "VISION"
            assert result["old_bytes"] == len(SEED_CONTENT["VISION"].encode("utf-8"))
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
                conn,
                PROJECT_A,
                "VISION",
                SEED_CONTENT["VISION"],
                99,
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
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "WISPS",
                    card_document("# body that is long enough\n"),
                    None,
                    base_updated_at=SEED_UPDATED_AT,
                )
        finally:
            conn.close()

    def test_replace_stale_base_conflicts_and_preserves_row(
        self,
        tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.replace_doc(
                conn,
                PROJECT_A,
                "VISION",
                SEED_CONTENT["VISION"] + "First writer.\n",
                1,
                base_updated_at=SEED_UPDATED_AT,
            )
            current = sd.get_doc(conn, PROJECT_A, "VISION")
            with pytest.raises(sd.StrategyDocConflictError) as exc:
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "VISION",
                    SEED_CONTENT["VISION"] + "Second writer, stale base.\n",
                    2,
                    base_updated_at=SEED_UPDATED_AT,
                )
            # Conflict teaching names the re-read recovery; the first
            # writer's content survives untouched.
            assert "doc get VISION" in str(exc.value)
            assert (
                sd.get_doc(conn, PROJECT_A, "VISION")["content"] == current["content"]
            )
        finally:
            conn.close()

    def test_replace_stale_base_identical_content_conflicts(
        self,
        tmp_db: str,
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
                conn,
                PROJECT_A,
                "VISION",
                landed,
                1,
                base_updated_at=SEED_UPDATED_AT,
            )
            current = sd.get_doc(conn, PROJECT_A, "VISION")
            assert current["updated_at"] != SEED_UPDATED_AT  # row advanced
            # Same content as the live row, but the now-stale seed base.
            with pytest.raises(sd.StrategyDocConflictError):
                sd.replace_doc(
                    conn,
                    PROJECT_A,
                    "VISION",
                    landed,
                    2,
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
                    conn,
                    PROJECT_A,
                    "VISION",
                    SEED_CONTENT["VISION"] + "x\n",
                    None,
                    base_updated_at="  ",
                )
        finally:
            conn.close()
