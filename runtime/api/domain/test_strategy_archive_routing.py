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

    def test_flagless_entry_never_prunes_the_archive_sibling(self, tmp_path: Path) -> None:
        # An entry without an explicit `archived` key comes from a caller that
        # is not archive-aware; it must write to active WITHOUT deleting a file
        # at the archive location by defaulting to active-and-prune.
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "arch\n", "archived": True}]
        )
        assert _archived(tmp_path, "FOO").is_file()
        write_rendered_files(tmp_path, [{"slug": "FOO", "file_text": "act\n"}])
        assert _active(tmp_path, "FOO").is_file()
        assert _archived(tmp_path, "FOO").is_file()  # not destroyed


class TestInstallWriterRelocation:
    def test_apply_strategy_files_prunes_relocated_sibling(self, tmp_path: Path) -> None:
        from yoke_cli.project_install.strategy import apply_strategy_files
        from yoke_contracts.project_contract.strategy_docs_header import render_file_text

        # A checkout installed while FOO was active holds a clean active render.
        text = render_file_text("FOO", "2026-01-01T00:00:00Z", "# FOO\n\nbody\n")
        active = _active(tmp_path, "FOO")
        active.parent.mkdir(parents=True)
        active.write_text(text, encoding="utf-8")

        # FOO is now archived in the DB, so refresh's bundle carries it at the
        # archive location; applying it must prune the stale active sibling.
        entry = {
            "path": ".yoke/strategy/archive/FOO.md",
            "content": text,
            "install_policy": "db_render",
        }
        apply_strategy_files(tmp_path, [entry], {})
        assert _archived(tmp_path, "FOO").is_file()
        assert not active.exists()

    def test_apply_strategy_files_preserves_edited_relocated_sibling(
        self, tmp_path: Path,
    ) -> None:
        from yoke_cli.project_install.strategy import apply_strategy_files
        from yoke_contracts.project_contract.strategy_docs_header import render_file_text

        # A stale sibling with un-ingested local edits (header body-hash mismatch)
        # is preserved + warned, not silently destroyed.
        clean = render_file_text("FOO", "2026-01-01T00:00:00Z", "# FOO\n\nbody\n")
        first_line = clean.partition("\n")[0]
        active = _active(tmp_path, "FOO")
        active.parent.mkdir(parents=True)
        active.write_text(first_line + "\n# FOO\n\nHAND-EDITED body\n", encoding="utf-8")

        entry = {
            "path": ".yoke/strategy/archive/FOO.md",
            "content": clean,
            "install_policy": "db_render",
        }
        _map, _written, _unchanged, _preserved, warnings = apply_strategy_files(
            tmp_path, [entry], {}
        )
        assert active.exists()  # not destroyed
        assert any("stale copy of a relocated strategy doc" in w for w in warnings)


class TestIngestReadResolvesArchive:
    def test_read_ingest_files_finds_archived_doc(self, tmp_path: Path) -> None:
        write_rendered_files(
            tmp_path, [{"slug": "FOO", "file_text": "archived-body\n", "archived": True}]
        )
        files = read_ingest_files(tmp_path, ["FOO"])
        assert files[0]["text"] == "archived-body\n"
        assert files[0]["path"].endswith("archive/FOO.md")
