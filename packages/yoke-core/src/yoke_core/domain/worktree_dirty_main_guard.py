"""Scoped dirty-main guard for worktree creation.

``git worktree add`` copies HEAD, so a clean main is not required. The
invariant is overlap: refuse only when uncommitted main paths match what
the new lane needs. An empty needed-path set does not block, which stops
unrelated main dirt from serializing the fleet. Overlap refusals name
likely holders on this machine and include a ``yoke say --session`` recipe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.conflict_survey_declared_paths import (
    clean_path,
    matching_scope,
)
from yoke_core.domain.file_budget_paths import (
    FILE_BUDGET_SECTION,
    extract_file_budget_section_paths,
)
from yoke_core.domain.sessions_list_read import LIVENESS_ACTIVE
from yoke_core.domain.worktree_paths import _run


_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")
_UNTRACKED_EXEMPT_NAMES = frozenset({"runtime/config"})
_HOLDER_CAP = 3
_PATH_LIST_CAP = 20


@dataclass(frozen=True)
class DirtyMainVerdict:
    """Outcome of the scoped dirty-main check for one item."""

    blocked: bool
    kind: str
    paths: tuple[str, ...]
    needed_paths: tuple[str, ...]
    narrative: str


def _overlap(needed: Sequence[str], dirty: Sequence[str]) -> tuple[str, ...]:
    return tuple(path for path in dirty if path and matching_scope(needed, [path]))


def list_dirty_main_paths(
    repo_root: str,
    *,
    worktrees_dir: str = "",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(tracked_or_staged, untracked)`` dirty paths on main."""
    tracked_run = _run(["git", "-C", repo_root, "diff", "--name-only"])
    staged_run = _run(["git", "-C", repo_root, "diff", "--name-only", "--cached"])
    tracked = tuple(
        sorted(
            {
                path.strip()
                for path in (tracked_run.stdout + "\n" + staged_run.stdout).splitlines()
                if path.strip()
            }
        )
    )
    untracked_run = _run(
        [
            "git",
            "-C",
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
        ]
    )
    worktrees_rel = ""
    if worktrees_dir:
        worktrees_rel = os.path.relpath(worktrees_dir, repo_root).rstrip("/")
    untracked = tuple(
        path.strip()
        for path in untracked_run.stdout.splitlines()
        if path.strip()
        and path.strip() not in _UNTRACKED_EXEMPT_NAMES
        and not (worktrees_rel and path.strip().startswith(worktrees_rel + "/"))
    )
    return tracked, untracked


def overlapping_dirty_main(
    repo_root: str,
    needed_paths: Sequence[str] = (),
    *,
    worktrees_dir: str = "",
) -> tuple[bool, str, tuple[str, ...]]:
    """Return ``(blocked, kind, overlapping_paths)`` for this lane's paths.

    Empty *needed_paths* never blocks, even when main is dirty.
    """
    from yoke_core.domain.worktree_preflight_steps import (
        BLOCK_DIRTY_TRACKED,
        BLOCK_DIRTY_UNTRACKED,
    )

    needed = tuple(
        dict.fromkeys(clean_path(path) for path in needed_paths if clean_path(path))
    )
    if not needed:
        return False, "", ()
    tracked, untracked = list_dirty_main_paths(repo_root, worktrees_dir=worktrees_dir)
    tracked_hit = _overlap(needed, tracked)
    if tracked_hit:
        return True, BLOCK_DIRTY_TRACKED, tracked_hit
    untracked_hit = _overlap(needed, untracked)
    if untracked_hit:
        return True, BLOCK_DIRTY_UNTRACKED, untracked_hit
    return False, "", ()


def _dispatch(function_id: str, target: TargetRef, payload: dict | None = None):
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    return call_dispatcher(function_id=function_id, target=target, payload=payload)


def lane_needed_paths(item_id: int) -> tuple[str, ...]:
    """Union of survey touch paths, non-terminal claims, and File Budget."""
    collected: list[str] = []
    item = TargetRef(kind="item", item_id=int(item_id))
    try:
        survey = _dispatch("direct_workflow.conflict_survey.status", item)
        if survey.success:
            collected.extend((survey.result or {}).get("touch_paths") or [])
    except Exception:  # noqa: BLE001 - degrade; empty set must not serialize
        pass
    try:
        listed = _dispatch(
            "claims.path.list",
            item,
            {"states": list(_NON_TERMINAL_CLAIM_STATES)},
        )
        if listed.success:
            for claim in (listed.result or {}).get("claims") or []:
                collected.extend(claim.get("declared_paths") or [])
    except Exception:  # noqa: BLE001 - degrade; empty set must not serialize
        pass
    try:
        budget = _dispatch(
            "items.section.get",
            TargetRef(
                kind="section",
                item_id=int(item_id),
                section_name=FILE_BUDGET_SECTION,
            ),
        )
        if budget.success:
            collected.extend(
                extract_file_budget_section_paths(
                    str((budget.result or {}).get("content") or "")
                )
            )
    except Exception:  # noqa: BLE001 - degrade; empty set must not serialize
        pass
    return tuple(
        dict.fromkeys(clean_path(path) for path in collected if clean_path(path))
    )


def _on_main_lane(row: Mapping[str, Any]) -> bool:
    if str(row.get("work_role") or "") == "item":
        return True
    claims = row.get("claims") or []
    if not claims:
        return True
    return not any(claim.get("lane_role") for claim in claims)


def list_main_lane_holders(
    *,
    caller_session_id: str = "",
) -> tuple[dict[str, str], ...]:
    """Live same-machine sessions likely editing main, excluding the caller."""
    try:
        listed = _dispatch(
            "sessions.list",
            TargetRef(kind="global"),
            {"liveness": LIVENESS_ACTIVE},
        )
    except Exception:  # noqa: BLE001 - holder lookup is best-effort
        return ()
    if not listed.success:
        return ()
    rows = list((listed.result or {}).get("rows") or [])
    caller = str(caller_session_id or "")
    machine_id = ""
    for row in rows:
        if caller and str(row.get("session_id") or "") == caller:
            machine_id = str(row.get("machine_id") or "")
            break
    if not machine_id:
        return ()
    same = [
        row
        for row in rows
        if str(row.get("machine_id") or "") == machine_id
        and str(row.get("session_id") or "") != caller
    ]
    chosen = [row for row in same if _on_main_lane(row)] or same
    holders: list[dict[str, str]] = []
    for row in chosen[:_HOLDER_CAP]:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        holders.append(
            {
                "session_id": session_id,
                "actor_label": str(row.get("actor_label") or ""),
                "current_item": str(row.get("current_item") or row.get("focus") or ""),
            }
        )
    return tuple(holders)


def format_dirty_main_narrative(
    *,
    item_ref: str,
    kind: str,
    paths: Sequence[str],
    holders: Sequence[Mapping[str, str]] = (),
) -> str:
    """Render the sanctioned dirty-main refusal, including holder recipe."""
    from yoke_core.domain.worktree_preflight_steps import BLOCK_DIRTY_TRACKED

    kind_label = (
        "tracked or staged"
        if kind == BLOCK_DIRTY_TRACKED
        else "untracked, non-gitignored"
    )
    shown = list(paths)[:_PATH_LIST_CAP]
    listing = "\n  - ".join(shown)
    if len(paths) > _PATH_LIST_CAP:
        listing += f"\n  - ... +{len(paths) - _PATH_LIST_CAP} more"
    lines = [
        f"Cannot create worktree for {item_ref}: overlapping {kind_label} "
        "files on main match paths this lane needs. git worktree add copies "
        "HEAD and does not require a clean tree; this guard only refuses "
        "overlap.",
        f"  - {listing}",
    ]
    if holders:
        lines.append("Likely holder(s) working on main on this machine:")
        preview = ", ".join(shown[:8])
        ask = (
            "Please commit, stash, or drop overlapping dirty files on main: " + preview
        )
        for holder in holders:
            session_id = holder["session_id"]
            actor = holder.get("actor_label") or "unknown"
            focus = holder.get("current_item") or "(no current item)"
            lines.append(f"  session {session_id} actor={actor} focus={focus}")
            lines.append("Ask them to commit, stash, or drop the overlapping files:")
            lines.append(f"  yoke say --preview --session {session_id}")
            lines.append(
                f"  printf '%s\\n' {ask!r} | yoke say --session {session_id} --stdin"
            )
    else:
        lines.append(
            "No live session on this machine is recorded as working on main. "
            "Commit, stash, or drop the overlapping files, then retry. "
            f"Find peers with: yoke sessions list --liveness {LIVENESS_ACTIVE}"
        )
    return "\n".join(lines)


def evaluate_dirty_main_for_item(
    repo_root: str,
    *,
    item_id: int,
    item_ref: str,
    session_id: str = "",
    worktrees_dir: str = "",
    needed_paths: Sequence[str] | None = None,
) -> DirtyMainVerdict:
    """Resolve needed paths, overlap, and holder narrative for one item."""
    needed = (
        tuple(needed_paths) if needed_paths is not None else lane_needed_paths(item_id)
    )
    blocked, kind, paths = overlapping_dirty_main(
        repo_root, needed_paths=needed, worktrees_dir=worktrees_dir
    )
    if not blocked:
        return DirtyMainVerdict(False, "", (), tuple(needed), "")
    holders = list_main_lane_holders(caller_session_id=session_id)
    return DirtyMainVerdict(
        True,
        kind,
        paths,
        tuple(needed),
        format_dirty_main_narrative(
            item_ref=item_ref, kind=kind, paths=paths, holders=holders
        ),
    )


__all__ = [
    "DirtyMainVerdict",
    "evaluate_dirty_main_for_item",
    "format_dirty_main_narrative",
    "lane_needed_paths",
    "list_dirty_main_paths",
    "list_main_lane_holders",
    "overlapping_dirty_main",
]
