"""GitHub-facing epic task sync helpers.

Contains the shared label/issue-probe helpers. Per-task label and body
sync live in ``epic_task_sync_github_task_updates``; backfill helpers
live in ``epic_task_sync_github_backfill``; issue-creation and dedup
helpers live in ``epic_task_sync_github_create``. All are re-exported
here so existing ``_etsg.<name>`` patch points still resolve. The two
high-volume orchestrators (``sync_progress_notes`` and
``sync_epic_tasks``) live in ``epic_task_sync_github_core``.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

from typing import Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)

import yoke_core.domain.epic_task_sync as _epic_task_sync_parent
from yoke_core.domain import backlog_github_label_sync_rest as _label_rest
from yoke_core.domain import github_rest
from yoke_core.domain.epic_task_sync import (  # noqa: F401 — _task_context is
    # a patch surface for the task-updates sibling's _etsg() accessor.
    LABEL_COLOR_DEFAULT,
    _task_context,
)
from yoke_core.domain.epic_task_sync_github_backfill import (
    backfill_task_titles,
    backfill_task_labels,
)
from yoke_core.domain.epic_task_sync_github_create import (
    _backfill_parent_gh_issue,
    _dedup_or_create_task_issue,
    _extract_issue_num,
    _resolve_or_create_epic_issue,
    _task_id_from_epic,  # noqa: F401 - retained patch/re-export surface
)
from yoke_core.domain.epic_task_sync_github_task_updates import (
    sync_task_body,
    sync_task_label,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def _is_dry_run() -> bool:
    """Delegate to parent module so test patches on epic_task_sync._is_dry_run are respected."""
    return _epic_task_sync_parent._is_dry_run()


def _github_budget_kwargs(
    timeout_seconds: Optional[float], max_attempts: Optional[int],
) -> dict[str, object]:
    pairs = (("timeout_seconds", timeout_seconds), ("max_attempts", max_attempts))
    return {name: value for name, value in pairs if value is not None}


__all__ = [
    "_ensure_label",
    "_validate_issue_in_repo",
    "_is_dry_run",
    "backfill_task_titles",
    "backfill_task_labels",
    "sync_task_label",
    "sync_task_body",
    "_resolve_or_create_epic_issue",
    "_dedup_or_create_task_issue",
    "_extract_issue_num",
    "_backfill_parent_gh_issue",
]


def _ensure_label(
    label: str,
    *,
    project: str,
    description: str = "",
    color: str = LABEL_COLOR_DEFAULT,
    dry_run: bool = False,
) -> None:
    """Idempotently ensure ``label`` exists in the project's bound repo."""
    if dry_run:
        return
    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        )
    except Exception:  # noqa: BLE001
        return
    try:
        _label_rest.ensure_label(
            label, color, auth.repo, token=auth.token,
            description=description,
        )
    except github_rest.RestTransportError:
        # Best-effort label creation — caller paths surface concrete
        # failures through their own typed exception handlers when the
        # mutating REST call (issue.create/edit) lands.
        return


def _validate_issue_in_repo(
    item_ref: str,
    issue_num: str,
    *,
    project: str,
    stderr: TextIO,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> bool:
    """Verify ``issue_num`` exists in the bound repo before mutation.

    Returns True only when the issue is confirmed present. Returns False
    with a typed-failure-class stderr line on every other outcome —
    rate-limited, permission denied, transient transport, true repo
    mismatch, or unknown-in-both. The diagnostic improvement vs the
    historic shape: the operator never sees the misleading "repo
    mismatch detected" line when the real cause is a rate limit or a
    token scope issue. Callers' boolean contract is preserved.
    """
    try:
        repo = resolve_project_github_auth(
            project or "yoke",
            required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
        ).repo
    except ProjectGithubAuthError as exc:
        print(
            f"Error: GitHub auth failed for YOK-{item_ref}: {exc}. Mutation skipped.",
            file=stderr,
        )
        return False

    try:
        issue = github_rest.get_issue(
            project=project or "yoke",
            number=int(issue_num),
            **_github_budget_kwargs(timeout_seconds, max_attempts),
        )
    except github_rest.RateLimitedError as exc:
        print(
            f"Error: rate-limited probing issue #{issue_num} for YOK-{item_ref} "
            f"in {repo}: {exc}. Mutation skipped; retry after the rate-limit window resets.",
            file=stderr,
        )
        return False
    except github_rest.RestAuthError as exc:
        print(
            f"Error: permission denied probing issue #{issue_num} for YOK-{item_ref} "
            f"in {repo}: {exc}. GitHub App access lacks permission for this repo.",
            file=stderr,
        )
        return False
    except github_rest.RestTransportError as exc:
        print(
            f"Error: transport failure probing issue #{issue_num} for YOK-{item_ref} "
            f"in {repo}: {exc}. Mutation skipped.",
            file=stderr,
        )
        return False
    if issue is not None:
        return True

    # 404 in the named repo. Probe the default Yoke repo to distinguish
    # "issue absent everywhere" from "repo mismatch with the default."
    if (project or "yoke") != "yoke":
        try:
            default_issue = github_rest.get_issue(
                project="yoke",
                number=int(issue_num),
                **_github_budget_kwargs(timeout_seconds, max_attempts),
            )
        except github_rest.RestTransportError:
            default_issue = None
        if default_issue is not None:
            print(
                f"Error: Repo mismatch for YOK-{item_ref} — issue #{issue_num} exists in the "
                f"default repo but NOT in {repo}",
                file=stderr,
            )
            print(
                "  The github_issue field was likely set before cross-project routing "
                "was configured.",
                file=stderr,
            )
            print(
                "  Run '/yoke doctor' to detect all mismatches, or manually migrate with:",
                file=stderr,
            )
            print(f"    1. Create a new issue in {repo}", file=stderr)
            print("    2. Update the github_issue field in the DB", file=stderr)
            print("    3. Close the orphaned issue in the default repo", file=stderr)
            return False

    print(
        f"Error: Issue #{issue_num} for YOK-{item_ref} not found in {repo} or the default repo",
        file=stderr,
    )
    return False
