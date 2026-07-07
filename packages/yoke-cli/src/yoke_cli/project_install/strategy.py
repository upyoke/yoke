"""Client-side strategy-file application for ``yoke project install``."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from yoke_cli.project_install.files import ProjectInstallError, sha256_text
from yoke_contracts.project_contract.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    slug_from_view_path,
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
    strategy_map = dict(old_map)
    written: List[str] = []
    unchanged: List[str] = []
    preserved: List[str] = []
    warnings: List[str] = []
    for entry in entries:
        rel, content = entry["path"], entry["content"]
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


__all__ = [
    "STRATEGY_INSTALL_POLICY",
    "apply_strategy_files",
    "assert_safe_strategy_paths",
]
