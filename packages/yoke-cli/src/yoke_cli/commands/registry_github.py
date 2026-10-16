"""GitHub repo-level entries for the aggregate ``yoke`` CLI registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.github import github_pr_create
from yoke_cli.commands.adapters.github_branch import github_branch_head
from yoke_cli.commands.adapters.github_open_work import github_open_work_list
from yoke_cli.commands.adapters.github_merge_queue import (
    github_merge_queue_apply,
    github_merge_queue_hold,
    github_merge_queue_readiness,
)
from yoke_cli.commands.adapters.github_release import (
    github_release_create_commit_tag,
)


AdapterFn = Callable[[List[str]], int]


GITHUB_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("github", "release", "create-commit-tag"): (
        "github.release.create_commit_tag",
        github_release_create_commit_tag,
    ),
    ("github", "pr", "create"): ("github.pr.create", github_pr_create),
    ("github", "branch", "head"): ("github.branch.head", github_branch_head),
    ("github", "open-work", "list"): (
        "github.open_work.list",
        github_open_work_list,
    ),
    ("github", "merge-queue", "apply"): (
        "github.merge_queue.apply",
        github_merge_queue_apply,
    ),
    ("github", "merge-queue", "hold"): (
        "github.merge_queue.hold",
        github_merge_queue_hold,
    ),
    ("github", "merge-queue", "readiness"): (
        "github.merge_queue.readiness",
        github_merge_queue_readiness,
    ),
}


__all__ = ["GITHUB_SUBCOMMAND_REGISTRY"]
