"""Tests for the build-time install-bundle tree writer."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.project_contract.managed_block import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_BLOCK_END,
)
from yoke_core.domain import install_bundle_tree_build as build
from yoke_core.domain.install_bundle import INSTALL_BUNDLE_SOURCE_DIRS
from yoke_core.domain.install_bundle_sources import INSTALL_BUNDLE_SOURCE_FILES
from yoke_core.domain.install_bundle_tree_build import (
    InstallBundleTreeError,
    bundle_files,
    write_tree,
)


def _seed_sources(root: Path) -> None:
    """Create the canonical source dirs (one file each) and root source files."""
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        if rel == "docs/public":
            (d / "index.md").write_text("# Root\n", encoding="utf-8")
            (d / "nav.yaml").write_text(
                "root: {title: Root, summary: Read, path: index.md}\n"
            )
        else:
            (d / "content.md").write_text(f"# {rel}\n", encoding="utf-8")
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(
            f"# {rel}\n{MANAGED_BLOCK_BEGIN}\nuniversal\n"
            f"{MANAGED_BLOCK_END}\n# Yoke Repo Internals\nprivate\n",
            encoding="utf-8",
        )


def _snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_write_tree_builds_a_byte_exact_tree(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_sources(repo)
    dest = tmp_path / "out"

    written = write_tree(target_root=repo, dest=dest)

    expected = {build.PACKAGE_MARKER, "docs/public/index.md", "docs/public/nav.yaml"}
    expected |= {
        f"{rel}/content.md" for rel in INSTALL_BUNDLE_SOURCE_DIRS if rel != "docs/public"
    }
    expected |= set(INSTALL_BUNDLE_SOURCE_FILES)
    assert {Path(p).relative_to(dest).as_posix() for p in written} == expected
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        for path in (repo / rel).iterdir():
            assert (dest / rel / path.name).read_bytes() == path.read_bytes()
    assert (dest / build.PACKAGE_MARKER).read_bytes() == build.PACKAGE_MARKER_BYTES


def test_agents_md_ships_only_the_managed_region(tmp_path) -> None:
    _seed_sources(tmp_path)

    files = bundle_files(target_root=tmp_path)

    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        source = (tmp_path / rel).read_bytes()
        if rel != "AGENTS.md":
            assert files[rel] == source
            continue
        text = files[rel].decode("utf-8")
        assert text.endswith(f"{MANAGED_BLOCK_END}\n")
        assert "Yoke Repo Internals" not in text


def test_source_symlink_ships_as_a_regular_file(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_sources(repo)
    (repo / "canonical-body.md").write_text("canonical body\n", encoding="utf-8")
    link = repo / "runtime/harness/claude/agents/linked.md"
    link.symlink_to(Path("../../../../canonical-body.md"))
    dest = tmp_path / "out"

    write_tree(target_root=repo, dest=dest)

    packed = dest / "runtime/harness/claude/agents/linked.md"
    assert packed.is_file() and not packed.is_symlink()
    assert packed.read_text(encoding="utf-8") == "canonical body\n"


def test_cache_junk_never_ships(tmp_path) -> None:
    _seed_sources(tmp_path)
    cache = tmp_path / INSTALL_BUNDLE_SOURCE_DIRS[0] / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-313.pyc").write_bytes(b"\0")
    (tmp_path / INSTALL_BUNDLE_SOURCE_DIRS[0] / ".DS_Store").write_bytes(b"\0")

    files = bundle_files(target_root=tmp_path)

    assert not any("__pycache__" in rel or ".DS_Store" in rel for rel in files)


def test_untracked_public_docs_never_ship(tmp_path) -> None:
    _seed_sources(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    (tmp_path / "docs/public/scratch.md").write_text("# Scratch\n[Broken](absent.md)\n")

    files = bundle_files(target_root=tmp_path)

    assert "docs/public/scratch.md" not in files
    assert "docs/public/index.md" in files


def test_missing_source_dir_refuses_before_writing(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_sources(repo)
    shutil.rmtree(repo / INSTALL_BUNDLE_SOURCE_DIRS[0])

    with pytest.raises(InstallBundleTreeError, match="source dir is missing"):
        write_tree(target_root=repo, dest=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_missing_root_source_file_refuses(tmp_path) -> None:
    _seed_sources(tmp_path)
    (tmp_path / INSTALL_BUNDLE_SOURCE_FILES[0]).unlink()

    with pytest.raises(InstallBundleTreeError, match="source file is missing"):
        bundle_files(target_root=tmp_path)


def test_root_source_file_without_shipping_boundary_is_refused(tmp_path) -> None:
    _seed_sources(tmp_path)
    (tmp_path / INSTALL_BUNDLE_SOURCE_FILES[0]).write_text("# no managed block\n")

    with pytest.raises(InstallBundleTreeError, match="lacks managed-block boundary"):
        bundle_files(target_root=tmp_path)


def test_invalid_public_corpus_refuses_before_writing(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_sources(repo)
    (repo / "docs/public/index.md").write_text("# Root\n\n[Absent](absent.md)\n")

    with pytest.raises(InstallBundleTreeError, match="LINK_TARGET_MISSING"):
        write_tree(target_root=repo, dest=tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("layout", ["empty", "installed", "other_source"])
def test_non_yoke_target_is_refused_without_mutation(tmp_path, layout) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    if layout != "empty":
        _seed_sources(repo)
        (repo / "pyproject.toml").write_text('[project]\nname = "customer"\n')
        if layout == "installed":
            shutil.rmtree(repo / "runtime")
    before = _snapshot(repo)

    with pytest.raises(
        InstallBundleTreeError, match="install_bundle_target_not_yoke_source"
    ) as raised:
        write_tree(target_root=repo, dest=tmp_path / "out")

    assert "full Yoke source checkout" in str(raised.value)
    assert _snapshot(repo) == before
    assert not (tmp_path / "out").exists()


def test_non_empty_destination_is_refused(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_sources(repo)
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "stale.md").write_text("previous build\n")

    with pytest.raises(InstallBundleTreeError, match="build_dest_not_empty"):
        write_tree(target_root=repo, dest=dest)
    assert sorted(p.name for p in dest.iterdir()) == ["stale.md"]
