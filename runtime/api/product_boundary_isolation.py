"""Subprocess isolation helpers for product-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def write_sitecustomize(
    tmp_path: Path,
    *,
    repo_root: Path,
    allowed_repo_paths: Iterable[Path],
) -> Path:
    """Return a PYTHONPATH dir that hides unrelated repo editable installs."""
    directory = tmp_path / "sitecustomize"
    directory.mkdir(parents=True, exist_ok=True)
    allowed = [str(path.resolve()) for path in allowed_repo_paths]
    content = f"""
from pathlib import Path
import sys

_REPO_ROOT = Path({str(repo_root.resolve())!r})
_ALLOWED = {{Path(path) for path in {json.dumps(allowed)}}}


def _under_repo(path):
    return path == _REPO_ROOT or _REPO_ROOT in path.parents


def _is_package_editable_source(path):
    # Editable installs of the Yoke packages put `packages/<name>/src` on
    # sys.path. These resolve to whichever checkout pip installed (often the
    # primary working tree, not a linked worktree), so an under-repo-root test
    # alone cannot recognize them. Match the structural shape instead.
    parts = path.parts
    return path.name == "src" and len(parts) >= 3 and parts[-3] == "packages"


def _keep(raw):
    if not raw:
        return True
    if str(raw).startswith("__editable__."):
        return False
    try:
        resolved = Path(raw).resolve()
    except OSError:
        return True
    # An omitted package's editable source must be pruned no matter which
    # checkout it points at; keep only the explicitly allowed sources.
    if _is_package_editable_source(resolved):
        return resolved in _ALLOWED
    return not _under_repo(resolved) or resolved in _ALLOWED


sys.path[:] = [raw for raw in sys.path if _keep(raw)]
sys.meta_path[:] = [
    finder
    for finder in sys.meta_path
    if not str(getattr(finder, "__module__", "")).startswith("__editable__")
]
sys.path_hooks[:] = [
    hook
    for hook in sys.path_hooks
    if not str(getattr(hook, "__module__", "")).startswith("__editable__")
]
sys.path_importer_cache.clear()

# Re-add the dependency site-packages so third-party deps (pydantic, etc.)
# stay importable after the under-repo prune above. On CI the .venv lives
# under the repo root, so the prune drops its site-packages; we must put the
# deps back. Editable Yoke packages install via .pth / __editable__ finders
# (removed above), and appending a directory does NOT reprocess .pth files, so
# repo source paths are not reintroduced. sysconfig.purelib is the
# cross-platform interpreter site-packages (the .venv on Linux CI); the
# Homebrew path stays only as a macOS-dev fallback. The old code used ONLY the
# Homebrew path, absent on Linux runners -> every dependency vanished.
import sysconfig
_pyver = "python" + str(sys.version_info.major) + "." + str(sys.version_info.minor)
_dependency_sites = []
_purelib = sysconfig.get_paths().get("purelib")
if _purelib:
    _dependency_sites.append(Path(_purelib))
_dependency_sites.append(Path("/opt/homebrew/lib") / _pyver / "site-packages")
for _dep in _dependency_sites:
    if _dep.exists():
        _dep_text = str(_dep)
        if _dep_text not in sys.path:
            sys.path.append(_dep_text)
"""
    (directory / "sitecustomize.py").write_text(content.lstrip(), encoding="utf-8")
    return directory
