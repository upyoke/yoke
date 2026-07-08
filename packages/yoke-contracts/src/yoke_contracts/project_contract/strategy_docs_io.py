"""Client-side filesystem helpers for rendered strategy docs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.project_contract.file_write import write_live_text
from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_view_path,
)

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class StrategyDocSlugError(ValueError):
    """Raised for a slug whose shape can never name a strategy doc."""


class StrategyIngestFileMissingError(FileNotFoundError):
    """Raised when a requested slug has no rendered file under target_root."""


def require_strategy_doc_slug(slug: str) -> str:
    """Validate a strategy-doc slug before using it as a filename."""
    if not slug or not _SLUG_RE.match(slug):
        raise StrategyDocSlugError(
            f"invalid strategy doc slug {slug!r}; slugs are [A-Za-z0-9_-]+ "
            "(they become .yoke/strategy/<slug>.md filenames)."
        )
    return slug


def read_ingest_files(
    target_root: Path,
    slugs: Sequence[str],
    *,
    validate_slug: Callable[[str], str] = require_strategy_doc_slug,
) -> List[Dict[str, str]]:
    """Read rendered files for ``slugs``; return ``[{slug, path, text}]``."""
    target_root = Path(target_root)
    files: List[Dict[str, str]] = []
    for slug_value in slugs:
        slug = validate_slug(str(slug_value))
        # A doc lives in exactly one location (the writer prunes the stale
        # sibling on any archive flip), so resolve active first, then the
        # archive subdir — archived docs stay editable-via-file.
        path = strategy_view_path(target_root, slug)
        if not path.is_file():
            archived_path = strategy_view_path(target_root, slug, archived=True)
            if archived_path.is_file():
                path = archived_path
        if not path.is_file():
            raise StrategyIngestFileMissingError(
                f"no rendered file for strategy doc {slug!r} at {path}; "
                "render it first: yoke strategy render --target-root "
                f"{target_root}"
            )
        files.append(
            {
                "slug": slug,
                "path": str(path),
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return files


def write_rendered_files(
    target_root: Path,
    files: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """Write rendered file texts under ``.yoke/strategy/``.

    Each entry's ``archived`` flag routes the doc between the active
    ``.yoke/strategy/<slug>.md`` location and the archived
    ``.yoke/strategy/archive/<slug>.md`` location. On every write the
    stale sibling at the *other* location is pruned, so an archive↔active
    flip leaves exactly one file for the slug. The ``archive/`` subdir is
    created lazily (by :func:`write_live_text`) only when an archived doc
    is actually written — a project with no archived docs never grows it.
    """
    target_root = Path(target_root)
    report: Dict[str, str] = {}
    for entry in files:
        file_text = entry.get("file_text")
        if not file_text:
            continue
        slug = require_strategy_doc_slug(str(entry["slug"]))
        archived = bool(entry.get("archived", False))
        path = strategy_view_path(target_root, slug, archived)
        # Prune the stale sibling at the OTHER location (a doc that just
        # flipped archived state left a file behind there).
        stale = strategy_view_path(target_root, slug, not archived)
        if stale != path and stale.is_file():
            stale.unlink()
        if path.is_file() and path.read_bytes() == file_text.encode("utf-8"):
            report[slug] = "unchanged"
            continue
        write_live_text(path, file_text)
        report[slug] = "written"
    return report


__all__ = [
    "StrategyDocSlugError",
    "StrategyIngestFileMissingError",
    "read_ingest_files",
    "require_strategy_doc_slug",
    "write_rendered_files",
]
