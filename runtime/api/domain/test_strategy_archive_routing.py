"""Unit tests for the archive dimension of the strategy path contract,
the archive-aware writer (route + prune + lazy mkdir), and ingest's
active-or-archive read resolution."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.strategy_docs_io import (
    read_ingest_files,
    write_rendered_files,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    STRATEGY_ARCHIVE_DIR_REL,
    is_archived_view_path,
    slug_from_view_path,
    strategy_archive_dir,
    strategy_view_rel_path,
)


class TestPathContract:
    def test_rel_path_routes_by_archived(self) -> None:
        assert strategy_view_rel_path("MISSION") == ".yoke/strategy/MISSION.md"
        assert (
            strategy_view_rel_path("MISSION", archived=True)
            == ".yoke/strategy/archive/MISSION.md"
        )

    def test_slug_from_view_path_accepts_both_locations(self) -> None:
        assert slug_from_view_path(".yoke/strategy/MISSION.md") == "MISSION"
        assert slug_from_view_path(".yoke/strategy/archive/MISSION.md") == "MISSION"

    def test_slug_from_view_path_rejects_deeper_nesting(self) -> None:
        assert slug_from_view_path(".yoke/strategy/archive/deep/X.md") is None
        assert slug_from_view_path(".yoke/strategy/other/X.md") is None

    def test_is_archived_view_path(self) -> None:
        assert is_archived_view_path(".yoke/strategy/archive/MISSION.md") is True
        assert is_archived_view_path(".yoke/strategy/MISSION.md") is False

    def test_archive_dir_constant(self) -> None:
        assert STRATEGY_ARCHIVE_DIR_REL == ".yoke/strategy/archive"
        assert strategy_archive_dir("/root").as_posix().endswith(
            ".yoke/strategy/archive"
        )


def _active(root: Path, slug: str) -> Path:
    return root / ".yoke/strategy" / f"{slug}.md"


def _archived(root: Path, slug: str) -> Path:
    return root / ".yoke/strategy/archive" / f"{slug}.md"


class TestArchiveAwareWriter:
    def test_active_write_does_not_create_archive_dir(self, tmp_path: Path) -> None:
        report = write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": False}]
        )
        assert report == {"FOO": "written"}
        assert _active(tmp_path, "FOO").is_file()
        # The archive dir is created lazily — a project with no archived docs
        # never grows it.
        assert not (tmp_path / ".yoke/strategy/archive").exists()

    def test_flip_to_archive_moves_file_and_prunes_active(self, tmp_path: Path) -> None:
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": False}]
        )
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": True}]
        )
        assert _archived(tmp_path, "FOO").is_file()
        assert not _active(tmp_path, "FOO").exists()

    def test_flip_back_to_active_prunes_archive(self, tmp_path: Path) -> None:
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": True}]
        )
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": False}]
        )
        assert _active(tmp_path, "FOO").is_file()
        assert not _archived(tmp_path, "FOO").exists()

    def test_unchanged_report_when_already_in_place(self, tmp_path: Path) -> None:
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": True}]
        )
        report = write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "body\n", "archived": True}]
        )
        assert report == {"FOO": "unchanged"}


class TestIngestReadResolvesArchive:
    def test_read_ingest_files_finds_archived_doc(self, tmp_path: Path) -> None:
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "archived-body\n", "archived": True}]
        )
        files = read_ingest_files(tmp_path, ["FOO"])
        assert files[0]["text"] == "archived-body\n"
        assert files[0]["path"].endswith("archive/FOO.md")
