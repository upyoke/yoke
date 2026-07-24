"""Tests for the packaged install-bundle tree materializer + drift detector."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import install_bundle_tree_sync as sync_mod
from yoke_core.domain.install_bundle_tree_sync import (
    InstallBundleTreeError,
    detect_drift,
    sync,
)


@pytest.fixture(autouse=True)
def _no_session(monkeypatch):
    # Clear the harness session so workspace_authority is a deterministic no-op,
    # regardless of where pytest's tmp_path lands relative to the free-path list.
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)


def _seed_sources(root: Path) -> None:
    """Create the canonical source dirs (one file each) and root source files."""
    for rel in sync_mod.INSTALL_BUNDLE_SOURCE_DIRS:
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "content.md").write_text(f"# {rel}\n", encoding="utf-8")
    for rel in sync_mod.INSTALL_BUNDLE_SOURCE_FILES:
        (root / rel).write_text(f"# {rel}\n", encoding="utf-8")


def test_sync_materializes_a_byte_exact_tree_from_empty(tmp_path) -> None:
    _seed_sources(tmp_path)

    report = sync(target_root=tmp_path)

    assert report["removed"] == []
    assert len(report["written"]) == (
        len(sync_mod.INSTALL_BUNDLE_SOURCE_DIRS)
        + len(sync_mod.INSTALL_BUNDLE_SOURCE_FILES)
    )
    # A second sync is a no-op — idempotent.
    again = sync(target_root=tmp_path)
    assert again == {"written": [], "removed": []}
    assert detect_drift(target_root=tmp_path) == []


def test_sync_removes_stale_packaged_files(tmp_path) -> None:
    _seed_sources(tmp_path)
    sync(target_root=tmp_path)
    rel0 = sync_mod.INSTALL_BUNDLE_SOURCE_DIRS[0]
    stale = tmp_path / sync_mod.PACKAGED_TREE_REL / rel0 / "orphan.md"
    stale.write_text("no source counterpart\n", encoding="utf-8")
    assert detect_drift(target_root=tmp_path)  # drift is visible

    report = sync(target_root=tmp_path)

    assert f"{rel0}/orphan.md" in report["removed"]
    assert not stale.exists()
    assert detect_drift(target_root=tmp_path) == []


def test_sync_materializes_symlink_as_regular_file(tmp_path) -> None:
    _seed_sources(tmp_path)
    # A source symlink pointing OUTSIDE the snapshot (as the real references/
    # adapter tree does) must land as a regular file carrying the target bytes.
    external = tmp_path / "canonical-body.md"
    external.write_text("canonical body\n", encoding="utf-8")
    agents_dir = tmp_path / "runtime/harness/claude/agents"
    link = agents_dir / "linked.md"
    link.symlink_to(Path("../../../../canonical-body.md"))

    sync(target_root=tmp_path)

    packed = (
        tmp_path / sync_mod.PACKAGED_TREE_REL
        / "runtime/harness/claude/agents/linked.md"
    )
    assert packed.is_file() and not packed.is_symlink()
    assert packed.read_text(encoding="utf-8") == "canonical body\n"
    assert detect_drift(target_root=tmp_path) == []


def test_detect_drift_reports_content_and_membership(tmp_path) -> None:
    _seed_sources(tmp_path)
    sync(target_root=tmp_path)
    rel0 = sync_mod.INSTALL_BUNDLE_SOURCE_DIRS[0]
    # Mutate a packaged file (content drift) and drop another (missing).
    (tmp_path / sync_mod.PACKAGED_TREE_REL / rel0 / "content.md").write_text(
        "tampered\n", encoding="utf-8"
    )
    rel1 = sync_mod.INSTALL_BUNDLE_SOURCE_DIRS[1]
    (tmp_path / sync_mod.PACKAGED_TREE_REL / rel1 / "content.md").unlink()

    drift = detect_drift(target_root=tmp_path)

    assert any("content drift" in d and rel0 in d for d in drift)
    assert any("missing packaged file" in d and rel1 in d for d in drift)


def test_stray_file_outside_declared_dirs_is_flagged_and_removed(
    tmp_path,
) -> None:
    _seed_sources(tmp_path)
    sync(target_root=tmp_path)
    packaged = tmp_path / sync_mod.PACKAGED_TREE_REL
    stray = packaged / "not-a-source-dir" / "junk.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("outside every declared subtree\n", encoding="utf-8")

    drift = detect_drift(target_root=tmp_path)

    assert any(
        "stray packaged file" in d and "not-a-source-dir/junk.md" in d
        for d in drift
    )
    report = sync(target_root=tmp_path)
    assert "not-a-source-dir/junk.md" in report["removed"]
    assert not stray.exists()
    assert detect_drift(target_root=tmp_path) == []


def test_packaged_tree_package_marker_is_not_stray(tmp_path) -> None:
    _seed_sources(tmp_path)
    sync(target_root=tmp_path)
    packaged = tmp_path / sync_mod.PACKAGED_TREE_REL
    marker = packaged / "__init__.py"
    marker.write_text("", encoding="utf-8")

    assert detect_drift(target_root=tmp_path) == []
    assert sync(target_root=tmp_path) == {"written": [], "removed": []}
    assert marker.is_file()


def test_dry_run_writes_nothing(tmp_path) -> None:
    _seed_sources(tmp_path)

    report = sync(target_root=tmp_path, dry_run=True)

    assert report["written"]  # would-write is reported
    assert not (tmp_path / sync_mod.PACKAGED_TREE_REL).exists()
    assert detect_drift(target_root=tmp_path)  # still drifted — nothing written


def test_missing_source_dir_raises(tmp_path) -> None:
    _seed_sources(tmp_path)
    # Remove one source dir's only file AND the dir itself.
    import shutil

    shutil.rmtree(tmp_path / sync_mod.INSTALL_BUNDLE_SOURCE_DIRS[0])

    with pytest.raises(InstallBundleTreeError, match="source dir is missing"):
        sync(target_root=tmp_path)


def test_root_source_files_are_snapshotted_and_guarded(tmp_path) -> None:
    _seed_sources(tmp_path)
    sync(target_root=tmp_path)
    file_rel = sync_mod.INSTALL_BUNDLE_SOURCE_FILES[0]
    packed = tmp_path / sync_mod.PACKAGED_TREE_REL / file_rel
    assert packed.is_file()
    # Content drift on a packaged root file is reported and repaired.
    packed.write_text("tampered\n", encoding="utf-8")
    assert any(
        "content drift" in d and file_rel in d
        for d in detect_drift(target_root=tmp_path)
    )
    sync(target_root=tmp_path)
    assert detect_drift(target_root=tmp_path) == []
    # A missing source root file raises, like a missing source dir.
    (tmp_path / file_rel).unlink()
    with pytest.raises(InstallBundleTreeError, match="source file is missing"):
        sync(target_root=tmp_path)
