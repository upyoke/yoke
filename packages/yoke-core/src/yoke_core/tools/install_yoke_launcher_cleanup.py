"""Cleanup helpers for the checkout-backed ``yoke`` launcher install."""

from __future__ import annotations

import csv
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse


YOKE_EDITABLE_PACKAGE_NAMES: Tuple[str, ...] = (
    "yoke",
    "yoke-cli",
    "yoke-core",
    "yoke-contracts",
    "yoke-harness",
)


def cleanup_stale_editable_yoke_metadata(
    package_names: Sequence[str] = YOKE_EDITABLE_PACKAGE_NAMES,
    *,
    stream=None,
) -> int:
    """Remove orphaned PEP 660 editable metadata left behind by pip.

    ``pip uninstall`` can report success while leaving an editable
    ``dist-info`` record whose ``direct_url.json`` still points at a removed
    worktree. The launcher install owns cleanup for those records because the
    launcher supplies package source paths from ``YOKE_HOME``.
    """
    removed = 0
    out = stream if stream is not None else sys.stdout
    for package_name in package_names:
        for dist_info in _editable_dist_info_dirs(package_name):
            editable_target = _editable_direct_url_target_from_dist_info(dist_info)
            if editable_target is None:
                continue
            removed_before = removed
            for path in _editable_distribution_paths_from_dist_info(dist_info):
                if path.is_dir():
                    shutil.rmtree(path)
                    removed += 1
                elif path.exists():
                    path.unlink()
                    removed += 1
            if removed > removed_before:
                out.write(
                    f"Removed stale editable metadata for {package_name} "
                    f"(target was {editable_target}).\n"
                )
    return removed


def _editable_dist_info_dirs(package_name: str) -> list[Path]:
    purelib = Path(sysconfig.get_path("purelib"))
    normalized = package_name.replace("-", "_").replace(".", "_")
    return sorted(purelib.glob(f"{normalized}-*.dist-info"))


def _editable_direct_url_target_from_dist_info(dist_info: Path) -> Optional[Path]:
    direct_url = dist_info / "direct_url.json"
    if not direct_url.is_file():
        return None
    try:
        raw = direct_url.read_text(encoding="utf-8")
    except OSError:
        return None
    return _editable_direct_url_target_from_text(raw)


def _editable_direct_url_target_from_text(raw: str) -> Optional[Path]:
    try:
        import json

        payload = json.loads(raw)
    except Exception:
        return None
    dir_info = payload.get("dir_info") if isinstance(payload, dict) else None
    if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
        return None
    url = str(payload.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _editable_distribution_paths_from_dist_info(dist_info: Path) -> list[Path]:
    site_root = dist_info.parent
    dist_prefix = dist_info.name.split("-", 1)[0]
    paths: list[Path] = []
    record = dist_info / "RECORD"
    try:
        rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
    except OSError:
        rows = []
    for row in rows:
        if not row:
            continue
        raw = row[0]
        if ".dist-info/" in raw or raw.startswith("__editable__."):
            paths.append(site_root / raw)
    paths.extend(site_root.glob(f"__editable__.*{dist_prefix}*.pth"))
    paths.extend(site_root.glob(f"__editable__*{dist_prefix}*_finder.py"))
    paths.append(dist_info)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return sorted(unique, key=lambda path: len(path.parts), reverse=True)


__all__ = [
    "YOKE_EDITABLE_PACKAGE_NAMES",
    "cleanup_stale_editable_yoke_metadata",
]
