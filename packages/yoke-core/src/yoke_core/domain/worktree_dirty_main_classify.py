"""Untracked-vs-source-root classification for the dirty-main guard.

Repo-root (and other non-package-root) scratch is a warning. Untracked
paths under declared package roots — or any nested path when roots are
unknown — can collide with a new module and still block.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.conflict_survey_declared_paths import clean_path


_PATH_LIST_CAP = 20


def under_source_root(path: str, prefixes: Sequence[str]) -> bool:
    cleaned = clean_path(path)
    if not cleaned:
        return False
    roots = tuple(clean_path(raw).rstrip("/") for raw in prefixes if clean_path(raw))
    if roots:
        return any(cleaned == root or cleaned.startswith(root + "/") for root in roots)
    return "/" in cleaned


def decide_dirty_main(
    needed_paths: Sequence[str],
    tracked: Sequence[str],
    untracked: Sequence[str],
    source_root_prefixes: Sequence[str] = (),
) -> tuple[bool, str, tuple[str, ...], tuple[str, ...]]:
    """Return ``(blocked, kind, block_paths, scratch_paths)``."""
    from yoke_core.domain.conflict_survey_declared_paths import matching_scope
    from yoke_core.domain.worktree_preflight_steps import (
        BLOCK_DIRTY_TRACKED,
        BLOCK_DIRTY_UNTRACKED,
    )

    needed = tuple(
        dict.fromkeys(clean_path(path) for path in needed_paths if clean_path(path))
    )
    scratch = tuple(
        path for path in untracked if not under_source_root(path, source_root_prefixes)
    )
    tracked_hit = tuple(
        path for path in tracked if needed and path and matching_scope(needed, [path])
    )
    if tracked_hit:
        return True, BLOCK_DIRTY_TRACKED, tracked_hit, scratch
    under = tuple(
        path for path in untracked if under_source_root(path, source_root_prefixes)
    )
    if under:
        return True, BLOCK_DIRTY_UNTRACKED, under, scratch
    return False, "", (), scratch


def scratch_warning_note(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    shown = list(paths)[:_PATH_LIST_CAP]
    extra = (
        f" (+{len(paths) - _PATH_LIST_CAP} more)" if len(paths) > _PATH_LIST_CAP else ""
    )
    return (
        "Untracked files outside package roots on main are not a worktree "
        "block (git worktree add copies HEAD only): " + ", ".join(shown) + extra
    )


def lane_source_root_prefixes(item_id: int) -> tuple[str, ...]:
    """Architecture-model package roots, or empty for nested-path fallback."""
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )
    from yoke_core.domain.architecture_context_data import package_roots_from_model

    try:
        detail = call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={},
        )
        project = ((detail.result or {}).get("item") or {}).get("project") or {}
        project_id = str(project.get("id") or project.get("slug") or "")
    except Exception:  # noqa: BLE001 - missing roots still exempt repo-root scratch
        return ()
    if not project_id:
        return ()
    try:
        listed = call_dispatcher(
            function_id="project_structure.get",
            target=TargetRef(kind="project_structure", project_id=project_id),
            payload={"project_id": project_id, "family": "architecture_model"},
        )
    except Exception:  # noqa: BLE001 - missing roots still exempt repo-root scratch
        return ()
    if not listed.success:
        return ()
    entries = (listed.result or {}).get("entries") or []
    payload = entries[0].get("payload") if entries else None
    if not isinstance(payload, Mapping):
        return ()
    return tuple(
        dict.fromkeys(
            clean_path(root).rstrip("/")
            for pairs in package_roots_from_model(payload).values()
            for root, _layout in pairs
            if clean_path(root)
        )
    )


__all__ = [
    "decide_dirty_main",
    "lane_source_root_prefixes",
    "scratch_warning_note",
    "under_source_root",
]
