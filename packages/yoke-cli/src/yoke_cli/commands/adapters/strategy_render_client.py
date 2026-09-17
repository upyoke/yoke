"""Client-side strategy render payload and local-edit apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.project_contract.strategy_docs_io import (
    inspect_local_renders,
    local_render_known,
    write_rendered_files,
)

LOCAL_EDIT_CONFLICT_TEACHING = (
    "has local edits and the remote document changed. Write the edits "
    "back with `yoke strategy ingest {slug}` or move the file aside and "
    "re-render."
)


def build_render_payload(
    target_root: Path | str,
    *,
    slugs: Optional[Sequence[str]] = None,
    include_archives: bool = False,
) -> Dict[str, Any]:
    """Build ``strategy.render.run`` payload from the local rendered view.

    Empty slugs select the server's active corpus. ``known`` carries
    header identity from files that still parse, including locally
    edited bodies, so an unchanged remote omits ``file_text``.
    """
    payload: Dict[str, Any] = {}
    if slugs:
        payload["slugs"] = [str(slug) for slug in slugs]
    if include_archives:
        payload["include_archives"] = True
    known = local_render_known(Path(target_root))
    if known:
        payload["known"] = known
    return payload


def apply_rendered_docs(
    target_root: Path | str,
    docs: Iterable[Mapping[str, Any]],
) -> Tuple[Dict[str, str], List[str]]:
    """Write returned file texts, preserving dirty local edits.

    Returns ``(report, conflict_slugs)``. A conflict is a dirty local
    file whose remote row also changed (the response still carries
    ``file_text``). Unchanged remotes omit the body, so a dirty file
    stays on disk and reports ``local-edit``.
    """
    target_root = Path(target_root)
    dirty = {
        item.slug: item
        for item in inspect_local_renders(target_root)
        if item.dirty
    }
    conflicts: List[str] = []
    writable: List[Mapping[str, Any]] = []
    report: Dict[str, str] = {}
    for doc in docs:
        slug = str(doc.get("slug") or "")
        if not slug:
            continue
        if doc.get("file_text") and slug in dirty:
            conflicts.append(slug)
            continue
        if doc.get("file_text"):
            writable.append(doc)
        elif doc.get("unchanged"):
            report[slug] = "local-edit" if slug in dirty else "unchanged"
    report.update(write_rendered_files(target_root, writable))
    return report, conflicts


def conflict_message(slugs: Sequence[str]) -> str:
    parts = [
        f"{slug} {LOCAL_EDIT_CONFLICT_TEACHING.format(slug=slug)}"
        for slug in slugs
    ]
    return "error (local_edit_conflict): " + " ".join(parts)


__all__ = [
    "LOCAL_EDIT_CONFLICT_TEACHING",
    "apply_rendered_docs",
    "build_render_payload",
    "conflict_message",
]
