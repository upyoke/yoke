"""Per-task GitHub update helpers — status label and body sync.

Owns ``sync_task_label`` and ``sync_task_body`` for a single epic task's
linked GitHub issue. Both are re-exported by ``epic_task_sync_github``
(the ``_etsg.*`` patch surface) and reached by callers through
``epic_task_sync``'s lazy delegates.

Shared helpers (``_is_dry_run``, ``_validate_issue_in_repo``) resolve
through the live ``epic_task_sync_github`` module at call time so test
patches on that module keep reaching them.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import backlog_github_body_writer as _writer
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain import project_label_policy
from yoke_core.domain.epic_task_sync import LABEL_COLOR_DEFAULT
from yoke_core.domain.epic_task_sync_github_create import _task_id_from_epic
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


def _etsg():
    """Live ``epic_task_sync_github`` module (call-time patch target).

    ``_is_dry_run`` / ``_validate_issue_in_repo`` / ``_task_context`` /
    ``resolve_project_github_auth`` all resolve through this accessor so
    test patches on ``epic_task_sync_github.<name>`` keep reaching them.
    """
    from yoke_core.domain import epic_task_sync_github as mod
    return mod


def sync_task_label(
    epic_id: str,
    task_num: int,
    new_status: str,
    *,
    conn: Optional[Any] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    stderr = stderr or sys.stderr

    if _etsg()._is_dry_run():
        print(
            f"[DRY-RUN] Skipping GitHub: label-sync for {epic_id}/{task_num}",
            file=stderr,
        )
        return 0

    context = _etsg()._task_context(epic_id, task_num, conn=conn)
    if context is None:
        return 0
    github_issue, project, repo, _body = context
    issue_num_str = github_issue.lstrip("#")
    if not issue_num_str or issue_num_str == "null":
        return 0
    issue_num = int(issue_num_str)

    gh_project = project or "yoke"
    if not github_sync_enabled(gh_project, conn=conn):
        print(github_sync_disabled_notice(gh_project, "task-label-sync"), file=stderr)
        return 0
    new_label = f"status:{new_status}"
    color = project_label_policy.get_color("label_color_status", LABEL_COLOR_DEFAULT)

    try:
        auth = _etsg().resolve_project_github_auth(gh_project)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: auth failed for sync_task_label: {exc}", file=stderr)
        return 1
    target_repo = repo or auth.repo

    try:
        _label_rest.ensure_label(
            new_label, color, target_repo, token=auth.token,
            description="Yoke status label",
        )
    except github_rest.RestTransportError as exc:
        print(f"Warning: failed to ensure label {new_label}: {exc}", file=stderr)

    try:
        labels = _label_rest.fetch_issue_labels(
            target_repo, issue_num, token=auth.token,
        )
    except github_rest.RestTransportError as exc:
        print(f"Warning: failed to fetch labels for #{issue_num}: {exc}", file=stderr)
        labels = []

    has_new = False
    for label in labels:
        if not label.startswith("status:"):
            continue
        if label == new_label:
            has_new = True
            continue
        try:
            _label_rest.remove_label(target_repo, issue_num, label, token=auth.token)
        except github_rest.RestTransportError as exc:
            print(f"Warning: failed to remove label {label}: {exc}", file=stderr)

    if not has_new:
        try:
            _label_rest.add_labels(
                target_repo, issue_num, [new_label], token=auth.token,
            )
        except github_rest.RestTransportError as exc:
            print(
                f"Warning: failed to add label {new_label} to #{issue_num}: {exc}",
                file=stderr,
            )
    return 0


def sync_task_body(
    epic_id: str,
    task_num: int,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if _etsg()._is_dry_run():
        print(
            f"[DRY-RUN] Skipping GitHub: body-sync for {epic_id}/{task_num}",
            file=stderr,
        )
        return 0

    context = _etsg()._task_context(epic_id, task_num, conn=conn)
    if context is None:
        return 0
    github_issue, project, repo, body = context
    issue_num_str = github_issue.lstrip("#")
    if not issue_num_str or issue_num_str == "null":
        return 0
    issue_num = int(issue_num_str)

    gh_project = project or "yoke"
    if not github_sync_enabled(gh_project, conn=conn):
        print(
            github_sync_disabled_notice(gh_project, "task-body-sync"),
            file=stderr,
        )
        return 0

    if not _etsg()._validate_issue_in_repo(
        f"{epic_id}/{task_num}",
        str(issue_num),
        repo,
        project=gh_project,
        stderr=stderr,
    ):
        print(
            f"Warning: sync-task-body skipped for {epic_id}/{task_num} — repo mismatch",
            file=stderr,
        )
        return 1

    write = _writer.update_issue_body_typed(
        project=gh_project,
        number=issue_num,
        body=body,
        item_fields={
            "title": f"{epic_id}/{task_num}",
            "status": "implementing",
            "type": "task",
            "project": gh_project,
            "identity": _writer.epic_task_identity(epic_id, task_num),
            "body_command": _writer.epic_task_body_command(epic_id, task_num),
            "next_actions": _writer.epic_task_next_actions(epic_id),
        },
        conn=conn,
        item_id=_task_id_from_epic(str(epic_id), int(task_num)),
        stderr=stderr,
    )

    if write.returncode != 0:
        print(
            f"Warning: Failed to sync task body for {epic_id}/{task_num} ({github_issue})",
            file=stderr,
        )
        return 1

    if write.is_compact:
        print(
            f"Synced task body: {epic_id}/{task_num} -> {github_issue} (compact mirror)",
            file=stdout,
        )
    else:
        print(f"Synced task body: {epic_id}/{task_num} -> {github_issue}", file=stdout)
    return 0


__all__ = ["sync_task_label", "sync_task_body"]
