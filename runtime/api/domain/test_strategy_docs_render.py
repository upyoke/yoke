"""Tests for the per-project byte-idempotent ``render_docs`` writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_header as hdr
from yoke_core.domain.strategy_docs_paths import strategy_view_path
from runtime.api.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    PROJECT_B,
    SEED_CONTENT,
    SEED_SLUGS,
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


def _seed(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_docs(conn)
    finally:
        conn.close()


class TestRenderDocs:
    def test_render_writes_header_plus_byte_faithful_body(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        _seed(tmp_db)
        target_root = tmp_path / "checkout"

        report = sd.render_docs(target_root=target_root, project_id=PROJECT_A)

        assert report == {slug: "written" for slug in SEED_SLUGS}
        for slug in SEED_SLUGS:
            text = strategy_view_path(target_root, slug).read_text(
                encoding="utf-8"
            )
            parsed = hdr.parse_file_text(text)
            assert parsed.slug == slug
            assert parsed.updated_at == SEED_UPDATED_AT
            assert parsed.body == SEED_CONTENT[slug]
            assert parsed.content_sha256 == hdr.content_sha256(
                SEED_CONTENT[slug]
            )

    def test_render_resolves_updated_by_actor_to_label(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        from yoke_core.domain.actors import resolve_actors_by_name

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            # The canonical seed provides the human actor labeled 'ben'.
            (editor,) = resolve_actors_by_name(conn, "ben")
            assert editor is not None
            conn.execute(
                "UPDATE actors SET name = %s WHERE id = %s",
                ("Ben Bauman", editor),
            )
            conn.execute(
                "UPDATE strategy_docs SET updated_by_actor_id = %s "
                "WHERE project_id = %s AND slug = %s",
                (editor, PROJECT_A, "VISION"),
            )
            conn.commit()
        finally:
            conn.close()

        target_root = tmp_path / "checkout"
        sd.render_docs(target_root=target_root, project_id=PROJECT_A)

        # The editor's actor id resolves to its label in the rendered header.
        vision = hdr.parse_file_text(
            strategy_view_path(target_root, "VISION").read_text(encoding="utf-8")
        )
        assert vision.updated_by == "Ben Bauman"
        assert "updated_by=Ben%20Bauman" in strategy_view_path(
            target_root, "VISION"
        ).read_text(encoding="utf-8").splitlines()[0]
        # A doc with no recorded editor stays label-free (field omitted), so
        # an unlabeled edit never plants a churn-y placeholder.
        mission = hdr.parse_file_text(
            strategy_view_path(target_root, "MISSION").read_text(encoding="utf-8")
        )
        assert mission.updated_by is None

    def test_second_render_is_byte_identical_and_unchanged(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        _seed(tmp_db)
        target_root = tmp_path / "checkout"

        sd.render_docs(target_root=target_root, project_id=PROJECT_A)
        first = {
            slug: strategy_view_path(target_root, slug).read_bytes()
            for slug in SEED_SLUGS
        }
        report = sd.render_docs(target_root=target_root, project_id=PROJECT_A)
        second = {
            slug: strategy_view_path(target_root, slug).read_bytes()
            for slug in SEED_SLUGS
        }

        # No wall-clock input anywhere: unchanged content renders
        # byte-identical, so tracked files produce no git diff.
        assert report == {slug: "unchanged" for slug in SEED_SLUGS}
        assert first == second

    def test_render_subset_via_slugs(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        _seed(tmp_db)
        target_root = tmp_path / "checkout"

        report = sd.render_docs(
            target_root=target_root, project_id=PROJECT_A, slugs=["PAD"],
        )

        assert report == {"PAD": "written"}
        assert strategy_view_path(target_root, "PAD").is_file()
        assert not strategy_view_path(target_root, "MISSION").exists()
        with pytest.raises(sd.StrategyDocMissingError):
            sd.render_docs(
                target_root=target_root, project_id=PROJECT_A,
                slugs=["NOT-A-DOC"],
            )

    def test_render_rewrites_only_replaced_doc(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        target_root = tmp_path / "checkout"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.render_docs(target_root=target_root, project_id=PROJECT_A)
            sd.replace_doc(
                conn, PROJECT_A, "PAD", SEED_CONTENT["PAD"] + "\nNew idea.\n",
                None, base_updated_at=SEED_UPDATED_AT,
            )
        finally:
            conn.close()

        report = sd.render_docs(target_root=target_root, project_id=PROJECT_A)

        assert report["PAD"] == "written"
        unchanged = {s for s in SEED_SLUGS if s != "PAD"}
        assert all(report[s] == "unchanged" for s in unchanged)

    def test_render_never_touches_other_project_files(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        root_a = tmp_path / "checkout-a"
        root_b = tmp_path / "checkout-b"
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, PROJECT_A)
            insert_doc(
                conn, PROJECT_B, "MISSION", "# B mission\n\nproject B body.\n",
            )
            conn.commit()
        finally:
            conn.close()

        report_b = sd.render_docs(target_root=root_b, project_id=PROJECT_B)

        assert report_b == {"MISSION": "written"}
        body_b = strategy_view_path(root_b, "MISSION").read_text(encoding="utf-8")
        assert "project B body" in body_b
        # Project A's checkout was never written.
        assert not root_a.exists()

    def test_render_empty_project_teaches_seed_defaults(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        # Projects 1 and 2 exist (schema seed); only A gets docs.
        _seed(tmp_db)
        with pytest.raises(sd.StrategyDocMissingError, match="seed-defaults"):
            sd.render_docs(
                target_root=tmp_path / "checkout", project_id=PROJECT_B,
            )


class TestRenderFileMapSelection:
    def test_omits_archives_when_include_archives_false(self, tmp_db: str) -> None:
        from yoke_core.domain.strategy_docs_render import render_file_map

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.set_doc_archived(conn, PROJECT_A, "PAD", archived=True)
            active = render_file_map(
                conn, PROJECT_A, include_archives=False,
            )
            full = render_file_map(conn, PROJECT_A, include_archives=True)
        finally:
            conn.close()
        assert "PAD" not in {row["slug"] for row in active}
        assert "PAD" in {row["slug"] for row in full}

    def test_known_match_omits_file_text(self, tmp_db: str) -> None:
        from yoke_contracts.project_contract.strategy_docs_header import (
            content_sha256,
        )
        from yoke_core.domain.strategy_docs_render import render_file_map

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            known = [{
                "slug": "MISSION",
                "updated_at": SEED_UPDATED_AT,
                "content_sha256": content_sha256(SEED_CONTENT["MISSION"]),
                "archived": False,
            }]
            rows = render_file_map(
                conn, PROJECT_A, ["MISSION"], known=known,
            )
        finally:
            conn.close()
        (row,) = rows
        assert row["unchanged"] is True
        assert "file_text" not in row

    def test_known_active_archived_returns_metadata_without_body(
        self, tmp_db: str,
    ) -> None:
        from yoke_contracts.project_contract.strategy_docs_header import (
            content_sha256,
        )
        from yoke_core.domain.strategy_docs_render import render_file_map

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.set_doc_archived(conn, PROJECT_A, "PAD", archived=True)
            known = [{
                "slug": "PAD",
                "updated_at": SEED_UPDATED_AT,
                "content_sha256": content_sha256(SEED_CONTENT["PAD"]),
                "archived": False,
            }]
            rows = render_file_map(
                conn, PROJECT_A, include_archives=False, known=known,
            )
        finally:
            conn.close()
        by_slug = {row["slug"]: row for row in rows}
        assert by_slug["PAD"]["archived"] is True
        assert by_slug["PAD"]["unchanged"] is False
        assert "file_text" not in by_slug["PAD"]

    def test_explicit_slug_renders_archived_doc(self, tmp_db: str) -> None:
        from yoke_core.domain.strategy_docs_render import render_file_map

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            sd.set_doc_archived(conn, PROJECT_A, "PAD", archived=True)
            rows = render_file_map(
                conn, PROJECT_A, ["PAD"], include_archives=False,
            )
        finally:
            conn.close()
        (row,) = rows
        assert row["slug"] == "PAD"
        assert row["archived"] is True
        assert row["file_text"]
