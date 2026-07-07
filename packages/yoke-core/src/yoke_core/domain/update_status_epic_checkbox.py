"""Parent-epic checkbox writeback for terminal-success task transitions (PAT REST).

When an epic task reaches terminal success, locate the parent epic's GitHub
issue body and flip the corresponding ``- [ ] #N`` checkbox to ``- [x] #N``.
The helper is a no-op when project auth is not configured, when the task or
parent issue have no ``github_issue`` value, or when the parent body
already shows the task as checked off.

The transformed body routes through the body-budget guard
(:func:`backlog_github_body_writer.select_body_for_github_transform`) so an
over-budget transformed parent body swaps to the compact mirror instead
of triggering ``GraphQL: Body is too long``.

GitHub I/O dispatches through
:mod:`yoke_core.domain.gh_rest_transport`. The legacy host-``gh`` path
has been retired; tests patch the REST transport surface directly.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_github_body_writer import (
    select_body_for_github_transform,
)
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _update_epic_checkbox(
    conn: Any,
    epic_id: str,
    task_num: str,
    new_status: str,
    github_issue: str,
    repo_args: list[str],
    project: str,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> None:
    from yoke_core.domain import update_status as _us  # late lookup honors test patches

    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if new_status not in TASK_TERMINAL_SUCCESS:
        return
    if not github_issue:
        return

    try:
        auth = resolve_project_github_auth(project)
    except ProjectGithubAuthError:
        return

    repo_string = ""
    if len(repo_args) >= 2 and repo_args[0] == "-R":
        repo_string = repo_args[1]
    if not repo_string:
        repo_string = auth.repo
    try:
        owner, repo = split_repo(repo_string)
    except ValueError:
        return

    task_issue_num = github_issue.lstrip("#")

    # Find parent item's github_issue
    p = _p(conn)
    parent_issue = query_scalar(
        conn,
        f"SELECT COALESCE(github_issue, '') FROM items WHERE CAST(id AS TEXT)=CAST({p} AS TEXT) LIMIT 1",
        (str(epic_id),),
    )
    if not parent_issue or parent_issue == "null":
        return
    parent_num = str(parent_issue).lstrip("#")
    if not parent_num:
        return

    if _us._is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: checkbox update on #{parent_num}", file=stdout)
        return

    # Fetch parent issue body via REST
    try:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/issues/{parent_num}",
            ),
            token=auth.token,
        )
    except RestNotFoundError:
        return
    except RestTransportError:
        return

    body_obj = resp.body if isinstance(resp.body, dict) else {}
    body = str(body_obj.get("body") or "")
    new_body = body.replace(
        f"- [ ] #{task_issue_num} ",
        f"- [x] #{task_issue_num} ",
    )

    if body == new_body:
        return

    try:
        epic_item_id = int(epic_id)
    except (TypeError, ValueError):
        epic_item_id = 0

    # Budget-check the transformed body. A compact mirror is selected when
    # the full body exceeds GitHub's body-size limit.
    final_body, mode = select_body_for_github_transform(
        body=new_body,
        item_fields={
            "title": f"epic {epic_id}",
            "status": "implementing",
            "type": "epic",
            "project": project,
        },
        conn=conn,
        item_id=epic_item_id,
    )

    try:
        request_with_retry(
            RestRequest(
                method="PATCH",
                path=f"/repos/{owner}/{repo}/issues/{parent_num}",
                body={"body": final_body},
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        print(
            f"Warning: Failed to check off task #{task_issue_num} on epic "
            f"issue #{parent_num}: {exc}",
            file=stderr,
        )
        return

    notice = " (compact mirror)" if mode == "compact" else ""
    print(
        f"Checked off task #{task_issue_num} on epic issue #{parent_num}{notice}",
        file=stdout,
    )
