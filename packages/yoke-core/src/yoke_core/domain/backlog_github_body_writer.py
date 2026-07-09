"""Shared GitHub issue body writer with compact-mirror budget guard.

Single entry point for every Yoke code path that creates or edits a
GitHub issue body carrying a rendered backlog item, epic, or epic-task
body. Picks compact-vs-full mode via the body-budget guard, dispatches
through the typed bearer-token REST surface
(:mod:`yoke_core.domain.github_rest`), and emits the compact-mode
telemetry notice.

Every full GitHub issue body mutation in this codebase MUST route
through :func:`update_issue_body_typed` (or the lower-level
:func:`backlog_github_body_budget.select_body_for_github`).

Callers that transform an existing GitHub issue body (e.g.,
``update_status_epic_checkbox`` flipping a checkbox) use
:func:`select_body_for_github_transform` so the resulting body is still
budget-checked before going to GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TextIO

from yoke_core.domain import backlog_github_body_budget as _budget
from yoke_core.domain import github_rest


def epic_task_identity(epic_id: str | int, task_num: str | int) -> str:
    return f"YOK-{epic_id} task {int(task_num)}"


def epic_task_body_command(epic_id: str | int, task_num: str | int) -> str:
    return (
        "python3 -m yoke_core.cli.db_router epic task-get-body "
        f"{epic_id} {int(task_num)}"
    )


def epic_task_next_actions(epic_id: str | int) -> list[str]:
    return [f"`{chr(47)}yoke conduct YOK-{epic_id}` — continue epic execution."]


@dataclass(frozen=True)
class BodyWriteResult:
    """Outcome of a budgeted GitHub body create/edit invocation."""

    returncode: int
    mode: _budget.SyncMode  # "full" or "compact"
    stdout: str
    stderr: str

    @property
    def is_compact(self) -> bool:
        return self.mode == "compact"


def update_issue_body_typed(
    *,
    project: str,
    number: int,
    body: str,
    item_fields: dict,
    conn: Optional[Any],
    item_id: int,
    stderr: Optional[TextIO] = None,
) -> BodyWriteResult:
    """Typed REST body update with compact-mirror budget guard.

    Selects compact-vs-full body via :func:`select_body_for_github`,
    dispatches a PATCH through :func:`github_rest.update_issue`, and
    surfaces the compact-mode notice on ``stderr``. Returns a
    :class:`BodyWriteResult` whose ``returncode`` is ``0`` on success and
    ``1`` on any :class:`github_rest.RestTransportError`.
    """
    selected_body, mode = _budget.select_body_for_github(
        body, item_fields=item_fields, conn=conn, item_id=item_id,
    )

    try:
        github_rest.update_issue(
            project=project, number=int(number), body=selected_body,
        )
    except github_rest.RestTransportError as exc:
        return BodyWriteResult(
            returncode=1, mode=mode, stdout="", stderr=str(exc),
        )

    if stderr is not None:
        _budget.emit_compact_notice(mode, item_fields.get("identity") or item_id, stderr)

    return BodyWriteResult(returncode=0, mode=mode, stdout="", stderr="")


def select_body_for_github_transform(
    *,
    body: str,
    item_fields: dict,
    conn: Optional[Any],
    item_id: int,
) -> tuple[str, _budget.SyncMode]:
    """Budget-check a body transformation before it goes to GitHub.

    Callers that compute a new body from an existing one (parent epic
    checkbox flips, task-list appends) use this to ensure an over-budget
    transformed body swaps to the compact mirror rather than reaching
    the REST issue-edit endpoint and triggering ``GraphQL: Body is too
    long``.
    """
    return _budget.select_body_for_github(
        body, item_fields=item_fields, conn=conn, item_id=item_id,
    )


__all__ = [
    "BodyWriteResult",
    "epic_task_body_command",
    "epic_task_identity",
    "epic_task_next_actions",
    "update_issue_body_typed",
    "select_body_for_github_transform",
]
