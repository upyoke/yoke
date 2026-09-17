"""Client-side filesystem helpers for rendered strategy docs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from yoke_contracts.project_contract.file_write import write_live_text
from yoke_contracts.project_contract.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_archive_dir,
    strategy_dir,
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


@dataclass(frozen=True)
class LocalRenderFile:
    """One on-disk rendered strategy file and whether its body is dirty."""

    slug: str
    archived: bool
    path: Path
    updated_at: Optional[str]
    content_sha256: Optional[str]
    dirty: bool
    dirty_reason: Optional[str]


def _inspect_one_render(path: Path, *, archived: bool) -> Optional[LocalRenderFile]:
    name = path.name
    if not name.endswith(".md"):
        return None
    slug = name[: -len(".md")]
    try:
        parsed = parse_file_text(path.read_text(encoding="utf-8"))
    except (OSError, StrategyHeaderError) as exc:
        reason = (
            "missing_or_mangled_header"
            if isinstance(exc, StrategyHeaderError) else "unreadable"
        )
        return LocalRenderFile(
            slug=slug, archived=archived, path=path,
            updated_at=None, content_sha256=None,
            dirty=True, dirty_reason=reason,
        )
    body_digest = content_sha256(parsed.body)
    dirty = body_digest != parsed.content_sha256 or parsed.slug != slug
    return LocalRenderFile(
        slug=slug,
        archived=archived,
        path=path,
        updated_at=parsed.updated_at,
        content_sha256=parsed.content_sha256,
        dirty=dirty,
        dirty_reason="body_does_not_match_header" if dirty else None,
    )


def inspect_local_renders(target_root: Path | str) -> List[LocalRenderFile]:
    """Inspect existing ``.yoke/strategy/`` files for refresh known-set."""
    files: List[LocalRenderFile] = []
    active_dir = strategy_dir(target_root)
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("*.md")):
            inspected = _inspect_one_render(path, archived=False)
            if inspected is not None:
                files.append(inspected)
    archive_dir = strategy_archive_dir(target_root)
    if archive_dir.is_dir():
        for path in sorted(archive_dir.glob("*.md")):
            inspected = _inspect_one_render(path, archived=True)
            if inspected is not None:
                files.append(inspected)
    return files


def local_render_known(target_root: Path | str) -> List[Dict[str, Any]]:
    """Header identity of local renders — the refresh ``known`` payload.

    Includes dirty files whose header still parses: the header is the
    last-known remote identity, so an unchanged remote can omit the body
    without losing the local edit.
    """
    known: List[Dict[str, Any]] = []
    for item in inspect_local_renders(target_root):
        if not item.updated_at or not item.content_sha256:
            continue
        known.append({
            "slug": item.slug,
            "updated_at": item.updated_at,
            "content_sha256": item.content_sha256,
            "archived": item.archived,
        })
    return known


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
        # flipped archived state left a file behind there) — but ONLY when the
        # entry explicitly declares its archived state. A flag-less entry comes
        # from a caller that is not archive-aware, and must never delete a file
        # at the other location by defaulting to active.
        if "archived" in entry:
            stale = strategy_view_path(target_root, slug, not archived)
            if stale != path and stale.is_file():
                stale.unlink()
        if path.is_file() and path.read_bytes() == file_text.encode("utf-8"):
            report[slug] = "unchanged"
            continue
        write_live_text(path, file_text)
        report[slug] = "written"
    return report


def relocate_generated_archive(
    target_root: Path | str,
    slug: str,
    *,
    updated_at: str,
    content_sha256: str,
) -> str:
    """Move or remove a generated active file after a remote archive.

    Dirty local bytes are left in place (``local-edit``). Matching
    generated identity is renamed into ``archive/``; a stale generated
    active file is unlinked without writing archive bytes.
    """
    target_root = Path(target_root)
    slug = require_strategy_doc_slug(slug)
    locals_ = {
        item.archived: item
        for item in inspect_local_renders(target_root)
        if item.slug == slug
    }
    active = locals_.get(False)
    archived_file = locals_.get(True)
    dest = strategy_view_path(target_root, slug, True)
    if (active is not None and active.dirty) or (
        archived_file is not None and archived_file.dirty
    ):
        return "local-edit"
    identity = (str(updated_at), str(content_sha256))
    if active is not None and active.path.is_file():
        matches = (
            str(active.updated_at or "") == identity[0]
            and str(active.content_sha256 or "") == identity[1]
        )
        if matches:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_file():
                dest.unlink()
            active.path.rename(dest)
            return "archived"
        active.path.unlink()
        return "removed"
    if archived_file is not None and archived_file.path.is_file():
        return "unchanged"
    return "archived"


__all__ = [
    "LocalRenderFile",
    "StrategyDocSlugError",
    "StrategyIngestFileMissingError",
    "inspect_local_renders",
    "local_render_known",
    "read_ingest_files",
    "relocate_generated_archive",
    "require_strategy_doc_slug",
    "write_rendered_files",
]
