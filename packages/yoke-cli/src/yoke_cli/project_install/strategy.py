"""Client-side strategy-file application for ``yoke project install``."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    sha256_text,
)
from yoke_contracts.project_contract.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    is_archived_view_path,
    slug_from_view_path,
    strategy_view_rel_path,
)

STRATEGY_INSTALL_POLICY = "db_render"


def assert_safe_strategy_paths(paths: Iterable[str]) -> None:
    """Refuse strategy entries outside ``.yoke/strategy/<slug>.md``."""
    for raw in paths:
        if slug_from_view_path(str(raw)) is None:
            raise ProjectInstallError(
                f"bundle names an unsafe strategy path {raw!r}: strategy "
                "entries must be flat .yoke/strategy/<slug>.md rendered "
                "views"
            )


def apply_strategy_files(
    repo_root: Path,
    entries: List[Dict[str, str]],
    old_map: Dict[str, str],
) -> Tuple[Dict[str, str], List[str], List[str], List[str], List[str]]:
    """Apply DB-render strategy entries without clobbering local edits."""
    assert_resolved_targets_within(
        repo_root,
        strategy_mutation_paths(entries),
        context="strategy file mutation",
    )
    strategy_map = dict(old_map)
    written: List[str] = []
    unchanged: List[str] = []
    preserved: List[str] = []
    warnings: List[str] = []
    for entry in entries:
        rel, content = entry["path"], entry["content"]
        # `rel` is this doc's authoritative location (active or archive/); if a
        # stale copy lingers at the OTHER location — a doc that was archived (or
        # unarchived) in the DB since this checkout last refreshed — prune it so
        # the checkout never carries two files for one slug.
        _prune_relocated_sibling(repo_root, rel, warnings)
        target = repo_root / rel
        if target.is_file():
            try:
                current = target.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                current = None
            if current is not None and current == content:
                strategy_map[rel] = sha256_text(content)
                unchanged.append(rel)
                continue
            if current is None or _has_uningested_edits(current):
                preserved.append(rel)
                warnings.append(
                    f"{rel} has local edits that never flowed back through "
                    "`yoke strategy ingest`; preserved -- ingest (or "
                    "discard) the edit, then rerun `yoke project refresh`"
                )
                continue
            if _bodies_match(current, content):
                # Only the render header drifted (the DB row's updated_at can
                # advance on a no-op re-save) — the doc body is byte-identical.
                # Keep the committed view: a metadata-only bump must not churn a
                # clean tracked file. Record the on-disk sha so the manifest
                # tracks what is actually on disk.
                strategy_map[rel] = sha256_text(current)
                unchanged.append(rel)
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        strategy_map[rel] = sha256_text(content)
        written.append(rel)
    return strategy_map, written, unchanged, preserved, warnings


def _prune_relocated_sibling(
    repo_root: Path, rel: str, warnings: List[str],
) -> None:
    """Remove a stale copy of a relocated strategy doc at its OTHER location.

    When a doc's authoritative location is ``rel`` (active or ``archive/``),
    any file for the same slug at the opposite location is a leftover from a
    pre-relocation refresh. Prune it unless it carries un-ingested local edits,
    in which case preserve it and warn — the same edit-safety stance the write
    path takes for the doc's own location.
    """
    slug = slug_from_view_path(rel)
    if slug is None:
        return
    sibling_rel = strategy_view_rel_path(slug, not is_archived_view_path(rel))
    assert_resolved_targets_within(
        repo_root, [sibling_rel], context="strategy sibling prune",
    )
    sibling = repo_root / sibling_rel
    if not sibling.is_file():
        return
    try:
        current = sibling.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        current = None
    if current is not None and _has_uningested_edits(current):
        warnings.append(
            f"{sibling_rel} is a stale copy of a relocated strategy doc but "
            "has un-ingested local edits; left in place — ingest (or discard) "
            "it, then rerun `yoke project refresh`"
        )
        return
    sibling.unlink()


def _has_uningested_edits(file_text: str) -> bool:
    try:
        header = parse_file_text(file_text)
    except StrategyHeaderError:
        return True
    return content_sha256(header.body) != header.content_sha256


def _bodies_match(current_text: str, new_text: str) -> bool:
    """True when two rendered views share a body, differing only in header.

    The render header carries the DB row's ``updated_at`` (and optional
    ``updated_by``), which advances on a no-op re-save while the body stays
    byte-identical. A body match means the only difference is metadata, so the
    installer keeps the committed file rather than churning it.
    """
    try:
        return parse_file_text(current_text).body == parse_file_text(new_text).body
    except StrategyHeaderError:
        return False


def strategy_mutation_paths(entries: List[Dict[str, str]]) -> List[str]:
    """All authoritative and opposite-location paths an apply can mutate."""
    paths: List[str] = []
    for entry in entries:
        rel = entry["path"]
        paths.append(rel)
        slug = slug_from_view_path(rel)
        if slug is not None:
            paths.append(
                strategy_view_rel_path(slug, not is_archived_view_path(rel))
            )
    return paths


__all__ = [
    "STRATEGY_INSTALL_POLICY",
    "apply_strategy_files",
    "assert_safe_strategy_paths",
    "strategy_mutation_paths",
]
