"""Required-label preparation for epic-task GitHub orchestration."""

from __future__ import annotations

from yoke_core.domain import project_label_policy
from yoke_core.domain.epic_task_sync import (
    LABEL_COLOR_DEFAULT,
    TYPE_LABEL_COLOR_DEFAULT,
    WORKTREE_LABEL_COLOR_DEFAULT,
)
from yoke_core.domain.github_constraints import clamp_label_name


def prepare_required_labels(project: str, *, dry_run: bool) -> tuple[str, str]:
    """Ensure shared epic/task labels and return status/worktree colors."""
    from yoke_core.domain import epic_task_sync_github as sync

    epic_color = project_label_policy.get_color("label_color_type_epic", "5319E7")
    task_color = project_label_policy.get_color(
        "label_color_type_task", TYPE_LABEL_COLOR_DEFAULT,
    )
    status_color = project_label_policy.get_color(
        "label_color_status", LABEL_COLOR_DEFAULT,
    )
    worktree_color = project_label_policy.get_color(
        "label_color_worktree", WORKTREE_LABEL_COLOR_DEFAULT,
    )
    sync._ensure_label(
        "type:epic", project=project, description="Epic (parent issue)",
        color=epic_color, dry_run=dry_run,
    )
    sync._ensure_label(
        "type:task", project=project, description="Task (child of epic)",
        color=task_color, dry_run=dry_run,
    )
    sync._ensure_label(
        "status:implementing", project=project,
        description="Task in implementation", color=status_color,
        dry_run=dry_run,
    )
    return status_color, worktree_color


def labels_for_task(
    project: str,
    status: str,
    worktree: str,
    *,
    status_color: str,
    worktree_color: str,
    dry_run: bool,
) -> list[str]:
    """Ensure one task's dynamic labels and return its issue label list."""
    from yoke_core.domain import epic_task_sync_github as sync

    status_label = f"status:{status}"
    sync._ensure_label(
        status_label, project=project, description=f"Task status: {status}",
        color=status_color, dry_run=dry_run,
    )
    labels = ["type:task", status_label]
    if worktree:
        worktree_label = clamp_label_name(
            f"worktree:{worktree.replace('/', '-')}"
        )
        sync._ensure_label(
            worktree_label, project=project, description=f"Worktree: {worktree}",
            color=worktree_color, dry_run=dry_run,
        )
        labels.append(worktree_label)
    return labels


__all__ = ["labels_for_task", "prepare_required_labels"]
