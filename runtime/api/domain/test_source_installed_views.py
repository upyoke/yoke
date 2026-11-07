"""A Yoke source checkout regenerates its installed-layout views from sources."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_contracts.project_contract.source_installed_views import (
    HARNESS_MANIFEST_SOURCES,
    SourceViewError,
    harness_manifest_view,
    refresh_source_installed_views,
    view_source,
)


def test_view_source_names_the_committed_source() -> None:
    assert view_source(".yoke/docs/agents/rules.md") == "docs/public/agents/rules.md"
    for rel in HARNESS_MANIFEST_SOURCES:
        assert view_source(harness_manifest_view(rel)) == rel
    assert view_source(".yoke/BOARD.md") == ".yoke/BOARD.md"


def _checkout(root: Path) -> Path:
    (root / "runtime/harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    for rel in HARNESS_MANIFEST_SOURCES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"source": "{rel}"}}\n')
    docs = root / "docs/public/guide"
    docs.mkdir(parents=True)
    (root / "docs/public/index.md").write_text("# Home\n")
    (docs / "setup.md").write_text("# Setup\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def test_views_copy_tracked_docs_and_harness_manifests(tmp_path) -> None:
    root = _checkout(tmp_path)
    (root / "docs/public/scratch.md").write_text("# Untracked\n")

    changed = refresh_source_installed_views(root)

    assert set(changed) == {
        ".yoke/docs/index.md",
        ".yoke/docs/guide/setup.md",
        ".yoke/harness/claude/manifest.json",
        ".yoke/harness/codex/manifest.json",
        ".yoke/harness/cursor/manifest.json",
    }
    assert (root / ".yoke/docs/guide/setup.md").read_text() == "# Setup\n"
    assert not (root / ".yoke/docs/scratch.md").exists()
    assert refresh_source_installed_views(root) == []


def test_views_follow_edits_and_drop_removed_pages(tmp_path) -> None:
    root = _checkout(tmp_path)
    refresh_source_installed_views(root)
    (root / "docs/public/index.md").write_text("# Home, edited\n")
    subprocess.run(
        ["git", "-C", str(root), "rm", "-qf", "docs/public/guide/setup.md"], check=True
    )
    (root / ".yoke/docs/stray.md").write_text("left behind\n")

    changed = refresh_source_installed_views(root)

    assert set(changed) == {
        ".yoke/docs/index.md",
        ".yoke/docs/guide/setup.md",
        ".yoke/docs/stray.md",
    }
    assert (root / ".yoke/docs/index.md").read_text() == "# Home, edited\n"
    assert not (root / ".yoke/docs/guide").exists()
    assert not (root / ".yoke/docs/stray.md").exists()


def test_view_symlink_is_replaced_by_a_copy(tmp_path) -> None:
    root = _checkout(tmp_path)
    view = root / ".yoke/docs/index.md"
    view.parent.mkdir(parents=True)
    view.symlink_to(root / "docs/public/index.md")

    assert ".yoke/docs/index.md" in refresh_source_installed_views(root)
    assert not view.is_symlink()
    assert view.read_text() == "# Home\n"


def test_other_projects_are_left_to_their_install(tmp_path) -> None:
    (tmp_path / ".yoke/docs").mkdir(parents=True)
    (tmp_path / ".yoke/docs/index.md").write_text("installed\n")

    assert refresh_source_installed_views(tmp_path) == []
    assert (tmp_path / ".yoke/docs/index.md").read_text() == "installed\n"


def test_missing_manifest_source_refuses_with_recovery(tmp_path) -> None:
    root = _checkout(tmp_path)
    (root / HARNESS_MANIFEST_SOURCES[0]).unlink()

    with pytest.raises(SourceViewError, match="source_view_source_unreadable"):
        refresh_source_installed_views(root)
