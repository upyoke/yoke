"""The one resolver for a project's rendered strategy-doc directory.

Every project's strategy corpus renders to ``.yoke/strategy/`` at that
project's repo root — Yoke's own checkout included. This module is the
single seam that knows the location: renderers, ingest, doctor checks,
lints, scheduler SML probes, and board widgets all resolve through these
helpers instead of carrying their own ``strategy/`` literals.

Future per-project override: when a ``projects``-level setting someday
carries a custom strategy dir, :func:`strategy_dir` grows a project
parameter and resolves it here — no caller changes. Deliberately NOT
built now (locked decision); the seam is this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

STRATEGY_DIR_REL = ".yoke/strategy"

_MD_SUFFIX = ".md"


def strategy_dir(target_root: Path | str) -> Path:
    """Return the rendered strategy-doc directory under ``target_root``."""
    return Path(target_root) / STRATEGY_DIR_REL


def strategy_view_rel_path(slug: str) -> str:
    """Repo-relative rendered-view path for one doc slug."""
    return f"{STRATEGY_DIR_REL}/{slug}{_MD_SUFFIX}"


def strategy_view_path(target_root: Path | str, slug: str) -> Path:
    """Absolute rendered-view path for one doc slug under ``target_root``."""
    return Path(target_root) / strategy_view_rel_path(slug)


def is_strategy_view_path(rel_path: str) -> bool:
    """True when a repo-relative path names a rendered strategy doc."""
    return slug_from_view_path(rel_path) is not None


def slug_from_view_path(rel_path: str) -> Optional[str]:
    """Extract the doc slug from a repo-relative rendered-view path.

    Returns ``None`` for paths outside ``.yoke/strategy/``, nested
    paths, or non-``.md`` files — callers use this both to recognize
    strategy views and to key the DB row lookup.
    """
    prefix = STRATEGY_DIR_REL + "/"
    if not rel_path.startswith(prefix):
        return None
    name = rel_path[len(prefix):]
    if "/" in name or not name.endswith(_MD_SUFFIX):
        return None
    slug = name[: -len(_MD_SUFFIX)]
    return slug or None


__all__ = [
    "STRATEGY_DIR_REL",
    "is_strategy_view_path",
    "slug_from_view_path",
    "strategy_dir",
    "strategy_view_path",
    "strategy_view_rel_path",
]
