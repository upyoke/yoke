"""Merge-worktree preparation data and context resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.merge_worktree_context import (
    MergeArgs,
    MergeContext,
    _matches_glob,  # noqa: F401 - preserved public import surface
)
from yoke_core.engines.merge_worktree_prepare_preflight import (  # noqa: F401
    preflight_checks,
)
from yoke_core.engines.merge_worktree_prepare_state import (  # noqa: F401
    _pre_merge_integration,
    _stash_classify_gate,
    check_and_clean_root_dirty_state,
    extract_generated_files,
    prune_agent_worktrees,
)


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


_TASK_TERMINAL_SUCCESS = ("done", "reviewed-implementation", "implemented", "release")


@dataclass
class ConflictInfo:
    """Per-file conflict classification."""

    path: str
    classification: str  # "generated", "doc", "yoke-gen", "additive", "overlapping"
    auto_resolvable: bool


def _sql_task_terminal_success_list() -> str:
    return ", ".join(f"'{s}'" for s in _TASK_TERMINAL_SUCCESS)


def validate_args(args: MergeArgs) -> Optional[str]:
    """Validate arguments. Returns error message or None."""
    if not args.branch:
        return (
            "Usage: python3 -m yoke_core.engines.merge_worktree "
            "[--local] [--keep-remote] [--skip-simulation] [--standalone] "
            "<branch> "
            "[target-branch] [epic-ref]"
        )

    return None


def resolve_context(args: MergeArgs) -> MergeContext:
    """Resolve full merge context from arguments."""
    from yoke_core.domain.worktree import resolve_main_root

    ctx = MergeContext(args=args)

    # Get repo root -- worktree-aware: resolve to the owning
    # main repo, not the CWD-relative worktree root.  This ensures all
    # downstream git operations (local target sync, branch cleanup, etc.)
    # run against the main repo even when the engine is invoked from a
    # worktree CWD.
    try:
        ctx.repo_root = resolve_main_root()
    except RuntimeError:
        raise RuntimeError("Not in a git repository")
    ctx.yoke_repo_root = ctx.repo_root

    # Resolve the branch's public item ref to the internal items.id every
    # downstream consumer expects. The ref carries the project sequence,
    # which is not the internal id once the two diverge, so it is passed
    # as ``public_ref`` for the dispatcher to resolve server-side — that
    # keeps resolution authoritative over an https control plane as well
    # as an in-process local connection, with no client DB read.
    ctx.item_id = str(args.item_id) if args.item_id is not None else None
    match = re.search(r"([A-Za-z][A-Za-z0-9]*-\d+)", args.branch)
    if ctx.item_id is None and match:
        try:
            detail = call_dispatcher(
                function_id="items.detail.get",
                target=TargetRef(kind="item", public_ref=match.group(1)),
                payload={},
            )
            if detail.success:
                item = (detail.result or {}).get("item") or {}
                if item.get("id") is not None:
                    ctx.item_id = str(item["id"])
        except Exception:  # noqa: BLE001 - DB context is advisory here.
            pass

    # Resolve epic ID the same way: PREFIX-N resolves through the project
    # sequence, a bare number is a project-local ref, both server-side.
    ctx.epic_id = args.epic_ref
    if ctx.epic_id:
        try:
            detail = call_dispatcher(
                function_id="items.detail.get",
                target=TargetRef(kind="item", public_ref=str(ctx.epic_id).strip()),
                payload={},
            )
            if detail.success:
                item = (detail.result or {}).get("item") or {}
                if item.get("id") is not None:
                    ctx.epic_id = str(item["id"])
        except Exception:  # noqa: BLE001 - DB context is advisory here.
            pass

    # Guard: an item branch with no epic lane is a standalone merge, which
    # carries item bookkeeping (merged_at, evidence, status) the engine does
    # not own. Callers declare that they own it by passing ``standalone``.
    if (
        not ctx.epic_id or ctx.epic_id == "null"
    ) and (ctx.item_id is not None or match is not None):
        if not args.standalone:
            raise RuntimeError(
                f"merge_worktree called for standalone item branch "
                f"'{args.branch}' without the standalone permission. "
                "Merge a standalone item branch with "
                "`yoke merge item <ITEM>`."
            )

    # Project-aware repo root resolution. Item/project reads and the
    # machine-local checkout mapping route through the transport-aware relay
    # so a non-yoke project's checkout + default branch resolve over an https
    # control plane; the checkout mapping itself stays machine-local.
    if ctx.item_id:
        try:
            detail = call_dispatcher(
                function_id="items.detail.get",
                target=TargetRef(kind="item", item_id=int(ctx.item_id)),
                payload={},
            )
            slug = None
            if detail.success:
                item = (detail.result or {}).get("item") or {}
                slug = (item.get("project") or {}).get("slug")
            if slug and slug != "yoke":
                from yoke_core.domain.project_checkout_locations import (
                    checkout_for_project_slug,
                )

                ctx.project = slug
                checkout = checkout_for_project_slug(slug)
                if checkout is None:
                    raise RuntimeError(
                        f"project '{ctx.project}' has no machine-local checkout mapping"
                    )
                ctx.repo_root = str(checkout)
                # Resolve default branch for non-yoke projects
                if not args.target or args.target == "main":
                    branch_resp = call_dispatcher(
                        function_id="projects.get",
                        target=TargetRef(kind="global"),
                        payload={"project": slug, "field": "default_branch"},
                    )
                    if branch_resp.success:
                        value = (branch_resp.result or {}).get("value")
                        if value:
                            args.target = value
            else:
                ctx.project = slug or None
        except Exception as exc:
            if args.item_id is not None:
                raise RuntimeError(
                    f"could not resolve project checkout for item {ctx.item_id}"
                ) from exc

    if args.expected_repo_root:
        expected_root = Path(args.expected_repo_root).resolve()
        resolved_root = Path(ctx.repo_root).resolve()
        if resolved_root != expected_root:
            raise RuntimeError(
                "resolved merge checkout does not match the item-bound checkout: "
                f"expected {expected_root}, got {resolved_root}"
            )

    if not args.target:
        from yoke_core.domain import project_settings

        args.target = project_settings.get_project_str(ctx.repo_root, "base_branch")

    # Resolve worktree path for branch
    ctx.worktree_path = _find_worktree(args.branch, ctx.repo_root)

    return ctx


def _find_worktree(branch: str, repo_root: str) -> str:
    """Find the worktree path for a branch, or fall back to repo root."""
    mw = _parent()
    result = mw._run_git(
        ["worktree", "list", "--porcelain"], cwd=repo_root, capture=True
    )
    if result.returncode != 0:
        return repo_root

    current_wt = ""
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_wt = line[len("worktree ") :]
        elif line == f"branch refs/heads/{branch}":
            return current_wt

    return repo_root
