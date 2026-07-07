"""Read the project install manifest's installer-rendered file set.

Shared by both line-gate classifiers — the source-dev
``yoke_core.domain.file_line_check_helpers`` and the product-client
``yoke_harness.git_hooks.file_line_check`` — which the package boundary
keeps as separate copies (harness must not import ``yoke_core``). Both
import this contracts helper so the manifest-reading logic itself is not
duplicated.

Installer-rendered files (the manifest ``files`` map) are upstream-authored
and rendered into the receiving repo — the committer cannot split them — so
the line gate treats them as GENERATED, not AUTHORED, in both the Yoke
source tree and any installed project.
"""

from __future__ import annotations

import functools
import json
import pathlib


INSTALL_MANIFEST_REL = ".yoke/install-manifest.json"


@functools.lru_cache(maxsize=64)
def _read_installer_managed(repo_root_str: str, _mtime_ns: int) -> frozenset[str]:
    manifest = pathlib.Path(repo_root_str) / INSTALL_MANIFEST_REL
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    files = data.get("files")
    if not isinstance(files, dict):
        return frozenset()
    return frozenset(str(p).replace("\\", "/") for p in files)


def installer_managed_paths(repo_root: pathlib.Path) -> frozenset[str]:
    """Posix paths the installer renders into ``repo_root`` (manifest ``files``).

    Empty when no manifest. Keyed by manifest mtime so a refresh that
    rewrites the manifest in the same commit is reflected without a stale
    cache, while a full-tree scan over thousands of files reads it once.
    """
    try:
        mtime = (repo_root / INSTALL_MANIFEST_REL).stat().st_mtime_ns
    except OSError:
        return frozenset()
    return _read_installer_managed(str(repo_root), mtime)


__all__ = ["INSTALL_MANIFEST_REL", "installer_managed_paths"]
