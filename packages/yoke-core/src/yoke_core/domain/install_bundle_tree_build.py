"""Build the packaged install-bundle tree from a Yoke source checkout.

``yoke_core.install_bundle_tree`` is the server tree a product wheel serves
through ``server_tree_root()``: byte-exact copies of the repo-root source dirs
plus the managed, project-agnostic region of the root doctrine files. The
repository commits only the sources; ``packages/yoke-core/setup.py`` calls
:func:`write_tree` while it builds a wheel or sdist. Source checkouts and
editable installs read the sources directly and never need this tree.
Enumeration materializes source symlinks as regular files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_core.domain.install_bundle import (
    DOCS_SOURCE,
    INSTALL_BUNDLE_SOURCE_DIRS,
    is_bundle_junk_path,
)
from yoke_core.domain.install_bundle_docs_validation import (
    public_corpus_files,
    validate_public_corpus,
)
from yoke_core.domain.install_bundle_sources import (
    INSTALL_BUNDLE_SOURCE_FILES,
    InstallBundleTreeError,
    source_file_bytes,
)

# The import package that makes ``yoke_core.install_bundle_tree`` resolvable
# through ``importlib.resources`` in an installed wheel.
PACKAGE_MARKER = "__init__.py"
PACKAGE_MARKER_BYTES = (
    b'"""Packaged install-bundle source tree for product-wheel local mode."""\n'
)


def relative_files(root: Path) -> List[str]:
    """POSIX-relative paths of every bundled file under ``root``.

    ``docs/public`` in a git checkout enumerates tracked pages only; other
    roots enumerate present files. Symlinks are followed, so a symlinked
    source file ships as a regular file. Cache junk never ships.
    """
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in public_corpus_files(root)
        if p.is_file() and not is_bundle_junk_path(p)
    )


def bundle_files(*, target_root: Path) -> Dict[str, bytes]:
    """Every packaged tree file, keyed by tree-relative path.

    Refuses, before returning anything, when ``target_root`` is not a Yoke
    source checkout, a declared source is missing, AGENTS.md lacks its
    managed-block boundary, or the public docs corpus fails validation.
    """
    repo = Path(target_root)
    if not is_yoke_source_checkout(repo):
        raise InstallBundleTreeError(
            f"install_bundle_target_not_yoke_source: {repo}. "
            "Build the yoke-core wheel from a full Yoke source checkout or "
            "its sdist."
        )
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        if not (repo / rel).is_dir():
            raise InstallBundleTreeError(
                f"install-bundle source dir is missing: {repo / rel}. "
                "Build from a full Yoke source checkout."
            )
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        if not (repo / rel).is_file():
            raise InstallBundleTreeError(
                f"install-bundle source file is missing: {repo / rel}. "
                "Build from a full Yoke source checkout."
            )
    refusals = validate_public_corpus(repo / DOCS_SOURCE)
    if refusals:
        raise InstallBundleTreeError("\n".join(str(r) for r in refusals))
    files: Dict[str, bytes] = {PACKAGE_MARKER: PACKAGE_MARKER_BYTES}
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        source = repo / rel
        for name in relative_files(source):
            files[f"{rel}/{name}"] = (source / name).read_bytes()
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        files[rel] = source_file_bytes(repo / rel)
    return files


def write_tree(*, target_root: Path, dest: Path) -> List[str]:
    """Write the packaged tree into the empty build directory ``dest``.

    Returns the written paths. Refuses a non-empty ``dest`` so a previous
    build's files can never survive into this one.
    """
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise InstallBundleTreeError(
            f"install_bundle_build_dest_not_empty: {dest}. "
            "Remove the stale build directory and rebuild."
        )
    written: List[str] = []
    for rel, data in sorted(bundle_files(target_root=target_root).items()):
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        written.append(str(path))
    return written


__all__ = [
    "PACKAGE_MARKER",
    "InstallBundleTreeError",
    "bundle_files",
    "relative_files",
    "write_tree",
]
