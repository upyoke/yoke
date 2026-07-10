"""GitHub side effects for epic-task status transitions (bearer-token REST).

Owns the three GitHub mutations performed on every epic-task status write:

- ``_github_label_sync``  -- reconcile the ``status:*`` label set on the
  task issue, creating the new label if missing and removing stale ones.
- ``_github_comment_post`` -- post a status-change comment with optional
  note body.
- ``_github_close_on_terminal`` -- close the task issue when the new status
  is in ``TASK_TERMINAL_SUCCESS``, with a verification round-trip and
  ``GitHubCloseFailure`` event emission on failure.

Each helper honors the dry-run env var and dispatches through the canonical
bearer-token REST transport (:mod:`yoke_core.domain.gh_rest_transport`).
``ProjectGithubAuthError`` from the canonical resolver and
``RestTransportError`` from the transport propagate so callers can surface
typed failures; helpers degrade with a warning for read-side paths.
"""

from __future__ import annotations

import json
from typing import Optional, TextIO, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import project_label_policy
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    quote_path_segment,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def _resolve_owner_repo(
    repo_args: list[str], project: str
) -> Optional[Tuple[str, str, str]]:
    """Resolve ``(owner, repo, token)`` for the call.

    ``repo_args`` carries the legacy ``["-R", "owner/name"]`` projection
    from upstream callers. It never selects the network target: when present,
    it must exactly match the repository in verified project auth. Empty args
    defer to the verified binding. Returns ``None`` on auth or projection
    failure so callers fail closed before issuing a REST request.
    """
    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError:
        return None

    if repo_args and repo_args != ["-R", auth.repo]:
        return None
    try:
        owner, name = split_repo(auth.repo)
    except ValueError:
        return None
    return owner, name, auth.token


def _github_label_sync(
    issue_num: str,
    new_status: str,
    repo_args: list[str],
    project: str,
    *,
    stderr: TextIO,
) -> None:
    from yoke_core.domain import update_status as _us  # late lookup honors test patches

    if _us._is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: label-reconcile for #{issue_num}", file=stderr)
        return

    resolved = _resolve_owner_repo(repo_args, project)
    if resolved is None:
        print(
            f"Warning: cannot resolve verified GitHub target for project "
            f"'{project}' on label-sync #{issue_num}",
            file=stderr,
        )
        return
    owner, repo, token = resolved

    new_label = f"status:{new_status}"
    color = project_label_policy.get_color("label_color_status", "C5DEF5")

    # Idempotent label create (422 means already-exists; proceed regardless).
    try:
        request_with_retry(
            RestRequest(
                method="POST",
                path=f"/repos/{owner}/{repo}/labels",
                body={
                    "name": new_label,
                    "color": color,
                    "description": "Yoke status label",
                },
            ),
            token=token,
        )
    except RestTransportError:
        pass

    # Fetch current labels on the issue.
    current_labels: list[str] = []
    try:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/issues/{issue_num}/labels",
            ),
            token=token,
        )
        body = resp.body
        if isinstance(body, list):
            current_labels = [
                str(entry.get("name", "")) for entry in body if isinstance(entry, dict)
            ]
    except RestTransportError:
        return

    has_new = False
    for label in current_labels:
        if not label.startswith("status:"):
            continue
        if label == new_label:
            has_new = True
            continue
        try:
            request_with_retry(
                RestRequest(
                    method="DELETE",
                    path=(
                        f"/repos/{owner}/{repo}/issues/{issue_num}/labels/"
                        f"{quote_path_segment(label)}"
                    ),
                ),
                token=token,
            )
        except RestTransportError:
            pass

    if not has_new:
        try:
            request_with_retry(
                RestRequest(
                    method="POST",
                    path=f"/repos/{owner}/{repo}/issues/{issue_num}/labels",
                    body={"labels": [new_label]},
                ),
                token=token,
            )
        except RestTransportError:
            print(f"Warning: failed to add label {new_label} to #{issue_num}", file=stderr)


def _github_comment_post(
    issue_num: str,
    old_status: str,
    new_status: str,
    note: str,
    repo_args: list[str],
    project: str,
    *,
    stderr: TextIO,
) -> None:
    from yoke_core.domain import update_status as _us  # late lookup honors test patches

    if _us._is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: comment-post for #{issue_num}", file=stderr)
        return

    resolved = _resolve_owner_repo(repo_args, project)
    if resolved is None:
        print(
            f"Warning: cannot resolve verified GitHub target for project "
            f"'{project}' on comment-post #{issue_num}",
            file=stderr,
        )
        return
    owner, repo, token = resolved

    if note:
        comment = f"**Status:** {old_status} → {new_status}\n{note}"
    else:
        comment = f"**Status:** {old_status} → {new_status}"

    try:
        request_with_retry(
            RestRequest(
                method="POST",
                path=f"/repos/{owner}/{repo}/issues/{issue_num}/comments",
                body={"body": comment},
            ),
            token=token,
        )
    except RestTransportError:
        print(f"Warning: failed to post comment on #{issue_num}", file=stderr)


def _github_close_on_terminal(
    issue_num: str,
    new_status: str,
    epic_id: str,
    task_num: str,
    repo_args: list[str],
    project: str,
    *,
    stderr: TextIO,
) -> None:
    from yoke_core.domain import update_status as _us  # late lookup honors test patches

    if new_status not in TASK_TERMINAL_SUCCESS:
        return

    if _us._is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: issue-close for #{issue_num}", file=stderr)
        return

    resolved = _resolve_owner_repo(repo_args, project)
    if resolved is None:
        print(
            f"Warning: cannot resolve verified GitHub target for project "
            f"'{project}' on close #{issue_num}",
            file=stderr,
        )
        return
    owner, repo, token = resolved

    close_failed_status: Optional[int] = None
    try:
        request_with_retry(
            RestRequest(
                method="PATCH",
                path=f"/repos/{owner}/{repo}/issues/{issue_num}",
                body={"state": "closed"},
            ),
            token=token,
        )
    except RestTransportError as exc:
        close_failed_status = exc.status or -1

    if close_failed_status is not None:
        _us._emit_event(
            "GitHubCloseFailure",
            epic_id=epic_id,
            task_num=task_num,
            context_json=json.dumps(
                {
                    "issue": int(issue_num),
                    "action": "close",
                    "status": close_failed_status,
                }
            ),
        )
        return

    # Verify the close round-trip.
    try:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/issues/{issue_num}",
            ),
            token=token,
        )
        body = resp.body if isinstance(resp.body, dict) else {}
        verify_state = str(body.get("state") or "").lower()
    except RestNotFoundError:
        return
    except RestTransportError:
        return

    if verify_state and verify_state != "closed":
        print(
            f"WARNING: REST close of #{issue_num} returned 200 but issue state is '{verify_state}'",
            file=stderr,
        )
        _us._emit_event(
            "GitHubCloseFailure",
            epic_id=epic_id,
            task_num=task_num,
            context_json=json.dumps(
                {"issue": int(issue_num), "action": "close-verify", "state": verify_state}
            ),
        )
