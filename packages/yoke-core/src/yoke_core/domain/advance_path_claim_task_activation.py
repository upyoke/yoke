"""Strict task-coverage preflight for path-claim activation."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.path_claim_task_bindings import pinned_task_claim_policy
from yoke_core.domain.path_claim_task_coverage import evaluate_task_coverage
from yoke_core.domain.project_identity import render_item_ref


def task_activation_block_reason(conn: Any, item_id: int) -> str | None:
    """Return a refusal for an unready per-task pin, otherwise ``None``."""
    try:
        task_scoped = pinned_task_claim_policy(conn, int(item_id))
    except Exception as exc:
        return (
            f"cannot resolve pinned task-scoped path-claim policy for "
            f"{render_item_ref(conn, item_id)}: {exc}"
        )
    if not task_scoped:
        return None
    result = evaluate_task_coverage(conn, int(item_id))
    if result.verdict == "pass":
        return None
    return result.reason


__all__ = ["task_activation_block_reason"]
