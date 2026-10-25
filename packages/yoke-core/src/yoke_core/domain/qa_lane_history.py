"""Check QA start commits against lane history locally or through its provider."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import standalone_item_merge_git as git


def checkout_contains(repo_root: str, head: str, commit: str) -> bool:
    answer, error = git.ancestry(repo_root, commit, head)
    if answer is None:
        raise ValueError(
            compose_refusal(
                f"qa_lane_history_unavailable: {error}",
                recovery="fetch the lane's commits into this checkout, then retry the gate",
            )
        )
    return answer


def item_lane_contains(conn: Any, item_id: int) -> Callable[[str, str], bool]:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id
    from yoke_core.domain.deployment_run_carried_work_repository import (
        open_repository_provider_source,
    )
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
    )

    provider = None

    @lru_cache(maxsize=None)
    def contains(head: str, commit: str) -> bool:
        nonlocal provider
        row = query_one(conn, "SELECT project_id FROM items WHERE id=%s", (item_id,))
        if row is None:
            return False
        checkout = checkout_for_project_id(row["project_id"])
        if checkout and Path(checkout).is_dir():
            return checkout_contains(str(checkout), head, commit)
        try:
            if provider is None:
                provider = open_repository_provider_source(conn, row["project_id"])
            return provider.contains_commit(head, commit) is True
        except CarriedWorkSourceUnavailable as exc:
            raise ValueError(
                compose_refusal(
                    f"qa_lane_history_unavailable: {exc}",
                    recovery="restore the project's repository Contents read binding, then retry the gate",
                )
            ) from exc

    return contains
