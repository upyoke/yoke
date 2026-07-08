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

# Archived docs render one level down, under ``.yoke/strategy/archive/``,
# so the live corpus directory only ever holds active docs. The whole
# subtree inherits the seeded ``.yoke/.gitignore`` ``strategy/`` rule, so
# archived views are gitignored local caches exactly like active ones.
STRATEGY_ARCHIVE_SUBDIR = "archive"
STRATEGY_ARCHIVE_DIR_REL = f"{STRATEGY_DIR_REL}/{STRATEGY_ARCHIVE_SUBDIR}"

_MD_SUFFIX = ".md"


def strategy_dir(target_root: Path | str) -> Path:
    """Return the rendered strategy-doc directory under ``target_root``."""
    return Path(target_root) / STRATEGY_DIR_REL


def strategy_archive_dir(target_root: Path | str) -> Path:
    """Return the archived-doc directory under ``target_root``.

    Created lazily by the writer only when an archived doc is actually
    rendered — a project with no archived docs never grows the subdir.
    """
    return Path(target_root) / STRATEGY_ARCHIVE_DIR_REL


def strategy_view_rel_path(slug: str, archived: bool = False) -> str:
    """Repo-relative rendered-view path for one doc slug.

    ``archived`` routes the slug into the ``archive/`` subdir so a doc's
    on-disk location tracks its archived state.
    """
    if archived:
        return f"{STRATEGY_ARCHIVE_DIR_REL}/{slug}{_MD_SUFFIX}"
    return f"{STRATEGY_DIR_REL}/{slug}{_MD_SUFFIX}"


def strategy_view_path(
    target_root: Path | str, slug: str, archived: bool = False
) -> Path:
    """Absolute rendered-view path for one doc slug under ``target_root``."""
    return Path(target_root) / strategy_view_rel_path(slug, archived)


def is_strategy_view_path(rel_path: str) -> bool:
    """True when a repo-relative path names a rendered strategy doc.

    Recognizes both the active ``.yoke/strategy/<slug>.md`` location and
    the archived ``.yoke/strategy/archive/<slug>.md`` location.
    """
    return slug_from_view_path(rel_path) is not None


def slug_from_view_path(rel_path: str) -> Optional[str]:
    """Extract the doc slug from a repo-relative rendered-view path.

    Accepts the active ``.yoke/strategy/<slug>.md`` path and the archived
    ``.yoke/strategy/archive/<slug>.md`` path, returning the slug for
    either. Returns ``None`` for paths outside ``.yoke/strategy/``, more
    deeply nested paths, or non-``.md`` files — callers use this both to
    recognize strategy views and to key the DB row lookup.
    """
    prefix = STRATEGY_DIR_REL + "/"
    if not rel_path.startswith(prefix):
        return None
    name = rel_path[len(prefix):]
    archive_prefix = STRATEGY_ARCHIVE_SUBDIR + "/"
    if name.startswith(archive_prefix):
        name = name[len(archive_prefix):]
    if "/" in name or not name.endswith(_MD_SUFFIX):
        return None
    slug = name[: -len(_MD_SUFFIX)]
    return slug or None


def is_archived_view_path(rel_path: str) -> bool:
    """True when a repo-relative path names an *archived* strategy view."""
    archive_prefix = STRATEGY_ARCHIVE_DIR_REL + "/"
    return (
        rel_path.startswith(archive_prefix)
        and slug_from_view_path(rel_path) is not None
    )


__all__ = [
    "STRATEGY_ARCHIVE_DIR_REL",
    "STRATEGY_ARCHIVE_SUBDIR",
    "STRATEGY_DIR_REL",
    "is_archived_view_path",
    "is_strategy_view_path",
    "slug_from_view_path",
    "strategy_archive_dir",
    "strategy_view_path",
    "strategy_view_rel_path",
]
