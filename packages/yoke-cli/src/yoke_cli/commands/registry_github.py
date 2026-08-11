"""GitHub repo-level entries for the aggregate ``yoke`` CLI registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.github import github_pr_create
from yoke_cli.commands.adapters.github_merge_queue import (
    github_merge_queue_apply,
)
from yoke_cli.commands.adapters.github_release import (
    github_release_create_next_tag,
)


AdapterFn = Callable[[List[str]], int]


GITHUB_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("github", "pr", "create"): ("github.pr.create", github_pr_create),
    ("github", "merge-queue", "apply"): (
        "github.merge_queue.apply",
        github_merge_queue_apply,
    ),
    ("github", "release", "create-next-tag"): (
        "github.release.create_next_tag",
        github_release_create_next_tag,
    ),
}


__all__ = ["GITHUB_SUBCOMMAND_REGISTRY"]
