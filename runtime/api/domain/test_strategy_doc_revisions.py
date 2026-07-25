"""Tests for the append-only strategy-doc revision history.

Every content write (create, replace, ingest) snapshots the NEW content
into ``strategy_doc_revisions`` in the same transaction as the doc-row
write; refused writes, no-op writes, and archive flips record nothing.
Storage shape and the append helper live in
``yoke_core.domain.strategy_docs_schema``; shared fixtures in
``strategy_docs_test_helpers``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_ingest as ing
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_docs_header import content_sha256
from yoke_core.domain.strategy_docs_schema import STRATEGY_DOC_REVISIONS_TABLE
from yoke_core.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
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


def fetch_revisions(conn, project_id: int, slug: str):
    return conn.execute(
        f"SELECT revision, content, content_sha256, byte_length, "
        f"source_operation, actor_id, created_at "
        f"FROM {STRATEGY_DOC_REVISIONS_TABLE} "
        "WHERE project_id = %s AND slug = %s ORDER BY revision",
        (project_id, slug),
    ).fetchall()


class TestReplace:
    def test_replace_snapshots_new_content(self, tmp_db: str) -> None:
        new_content = SEED_CONTENT["MISSION"] + "Sharper mission.\n"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = sd.replace_doc(
                conn, PROJECT_A, "MISSION", new_content, 42,
                base_updated_at=SEED_UPDATED_AT,
            )
            (rev,) = fetch_revisions(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert int(rev["revision"]) == 1
        assert str(rev["content"]) == new_content
        assert str(rev["content_sha256"]) == content_sha256(new_content)
        assert int(rev["byte_length"]) == len(new_content.encode("utf-8"))
        assert str(rev["source_operation"]) == "replace"
        assert int(rev["actor_id"]) == 42
        assert str(rev["created_at"]) == result["updated_at"]

    def test_sequence_increments_per_doc(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            insert_doc(conn, PROJECT_B, "PAD", "# B PAD\n\nproject B body.\n")
            conn.commit()
            first = sd.replace_doc(
                conn, PROJECT_A, "PAD", SEED_CONTENT["PAD"] + "Edit one.\n",
                None, base_updated_at=SEED_UPDATED_AT,
            )
            sd.replace_doc(
                conn, PROJECT_A, "PAD", SEED_CONTENT["PAD"] + "Edit two.\n",
                None, base_updated_at=first["updated_at"],
            )
            sd.replace_doc(
                conn, PROJECT_B, "PAD", "# B PAD\n\nproject B rewrite.\n",
                None, base_updated_at=SEED_UPDATED_AT,
            )
            a_revs = fetch_revisions(conn, PROJECT_A, "PAD")
            b_revs = fetch_revisions(conn, PROJECT_B, "PAD")
            mission_revs = fetch_revisions(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert [int(r["revision"]) for r in a_revs] == [1, 2]
        assert "Edit two." in str(a_revs[1]["content"])
        # Same slug in another project owns its own chain.
        assert [int(r["revision"]) for r in b_revs] == [1]
        # Untouched docs stay revision-free.
        assert mission_revs == []

    def test_refused_writes_record_nothing(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            with pytest.raises(sd.StrategyDocConflictError):
                sd.replace_doc(
                    conn, PROJECT_A, "MISSION",
                    SEED_CONTENT["MISSION"] + "Stale-base edit.\n",
                    None, base_updated_at="2020-01-01T00:00:00Z",
                )
            conn.rollback()
            # No-op write (identical content, fresh base) is not a content
            # write either.
            sd.replace_doc(
                conn, PROJECT_A, "MISSION", SEED_CONTENT["MISSION"],
                None, base_updated_at=SEED_UPDATED_AT,
            )
            revs = fetch_revisions(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert revs == []

    def test_archive_flip_records_nothing(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.set_doc_archived(conn, PROJECT_A, "MISSION", archived=True)
            revs = fetch_revisions(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert revs == []


class TestCreate:
    def test_create_records_first_revision(self, tmp_db: str) -> None:
        content = "# PLAYBOOK\n\nfresh doc body.\n"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            result = create_doc(conn, PROJECT_A, "PLAYBOOK", content, 7)
            (rev,) = fetch_revisions(conn, PROJECT_A, "PLAYBOOK")
        finally:
            conn.close()
        assert int(rev["revision"]) == 1
        assert str(rev["content"]) == content
        assert str(rev["content_sha256"]) == content_sha256(content)
        assert str(rev["source_operation"]) == "create"
        assert int(rev["actor_id"]) == 7
        assert str(rev["created_at"]) == result["updated_at"]


class TestIngest:
    @pytest.fixture
    def checkout(self, tmp_db: str, tmp_path: Path) -> Path:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
        finally:
            conn.close()
        root = tmp_path / "checkout"
        sd.render_docs(target_root=root, project_id=PROJECT_A)
        return root

    def test_written_doc_gains_revision(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        new_body = SEED_CONTENT["VISION"] + "Sharper vision.\n"
        edit_body(checkout, "VISION", new_body)
        conn = connect_test_db(tmp_db)
        try:
            plans = ing.plan_ingest(
                conn, project_id=PROJECT_A,
                files=ing.read_ingest_files(checkout, ["VISION", "MISSION"]),
            )
            results = {
                r["slug"]: r
                for r in ing.execute_ingest(
                    conn, plans, project_id=PROJECT_A, actor_id=9,
                )
            }
            (rev,) = fetch_revisions(conn, PROJECT_A, "VISION")
            unchanged_revs = fetch_revisions(conn, PROJECT_A, "MISSION")
        finally:
            conn.close()
        assert results["VISION"]["status"] == "written"
        assert int(rev["revision"]) == 1
        assert str(rev["content"]) == new_body
        assert str(rev["content_sha256"]) == content_sha256(new_body)
        assert str(rev["source_operation"]) == "ingest"
        assert int(rev["actor_id"]) == 9
        assert str(rev["created_at"]) == results["VISION"]["updated_at"]
        # Unchanged docs in the same batch record nothing.
        assert results["MISSION"]["status"] == "unchanged"
        assert unchanged_revs == []

    def test_conflict_records_nothing(
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
                conn, plans, project_id=PROJECT_A, actor_id=None,
            )
            revs = fetch_revisions(conn, PROJECT_A, "PAD")
        finally:
            conn.close()
        assert result["status"] == "conflict"
        assert revs == []
