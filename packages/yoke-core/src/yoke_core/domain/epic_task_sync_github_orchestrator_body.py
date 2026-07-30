"""Parent-epic body-append fallback for epic-task sync.

When the GitHub sub-issue REST endpoint is unavailable, the orchestrator
falls back to appending a ``## Tasks`` block to the parent epic's issue
body so subscribers can still see task links. The append routes through
:func:`backlog_github_body_writer.update_issue_body_typed` so an
over-budget appended body swaps to the compact mirror instead of being
rejected by the REST issue-edit endpoint.

The helper lives here (not inline in the orchestrator) so the
orchestrator stays under the file-line budget without sacrificing the
budget-guarded writer. Yoke does NOT use the ``gh`` CLI; every GitHub
interaction here goes through the typed
:mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

from typing import Any, TextIO

from yoke_core.domain import backlog_github_body_writer as _writer
from yoke_core.domain import github_rest


def scope_finalization_error(conn: Any, epic_id: int, stderr: TextIO) -> bool:
    """Finalize task scope before publication, returning whether it blocked."""
    from yoke_core.domain.epic_task_scope import (
        TaskScopeIncomplete,
        finalize_generated_task_scopes,
    )
    try:
        finalize_generated_task_scopes(conn, epic_id)
    except TaskScopeIncomplete as exc:
        print(f"Error: generated task publication blocked: {exc}", file=stderr)
        return True
    return False


def append_task_list_to_epic_body(
    *,
    epic_issue_num: str,
    gh_project: str,
    task_list_lines: list[str],
    parent_item_id: str,
    conn: Any,
    stderr: TextIO,
) -> None:
    body_addition = "\n\n---\n## Tasks\n" + "\n".join(task_list_lines) + "\n"
    try:
        current = github_rest.get_issue(
            project=gh_project, number=int(epic_issue_num),
        )
    except github_rest.RestTransportError:
        return
    if current is None:
        return
    new_body = (current.body or "") + body_addition
    epic_item_id = int(parent_item_id) if parent_item_id else 0
    _writer.update_issue_body_typed(
        project=gh_project,
        number=int(epic_issue_num),
        body=new_body,
        item_fields={
            "title": "",
            "status": "planning",
            "workflow_id": "epic",
            "project": gh_project,
        },
        conn=conn,
        item_id=epic_item_id,
        stderr=stderr,
    )


__all__ = ["append_task_list_to_epic_body", "scope_finalization_error"]
