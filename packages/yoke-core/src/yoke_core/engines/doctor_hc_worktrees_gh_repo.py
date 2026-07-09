"""Worktree health checks — wrong-repo GitHub issue migration (bearer-token REST).

Sibling of ``doctor_hc_worktrees_gh`` carrying ``hc_wrong_repo_issues``
and its private migration helper. GitHub auth + repo resolution flows
through the canonical
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
surface; the Yoke source repo is resolved dynamically rather than
hard-coded. REST helpers live in
:mod:`yoke_core.engines.doctor_hc_worktrees_gh_repo_rest`.

HC functions: HC-wrong-repo-issues
"""

from __future__ import annotations

import json
import re
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)

import yoke_core.engines.doctor_hc_worktrees as _wt
import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"
from yoke_core.engines.doctor_hc_worktrees_gh_repo_rest import (
    issue_close,
    issue_comment,
    issue_create,
    issue_delete,
    issue_view_full,
    issue_view_state,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_wrong_repo_issues(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-wrong-repo-issues: Wrong-repo GitHub issues.

    Resolves the Yoke source repo dynamically through the canonical
    resolver. SKIPs with the canonical reason when no GitHub App auth is configured
    for Yoke; FAIL only fires on other auth misconfigurations after a
    capability row exists.
    """
    if not _wt._github_auth_configured("yoke", db_path=args.db_path):
        rec.record(
            "HC-wrong-repo-issues", "Wrong-repo GitHub issues", "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project="yoke"),
        )
        return

    if not _base._table_exists(conn, "projects"):
        rec.record("HC-wrong-repo-issues", "Wrong-repo GitHub issues", "PASS", "")
        return

    # Resolve Yoke repo + auth dynamically.  Failure is a doctor FAIL.
    try:
        yoke_auth = resolve_project_github_auth("yoke", db_path=args.db_path)
    except ProjectGithubAuthError as err:
        rec.record(
            "HC-wrong-repo-issues", "Wrong-repo GitHub issues", "FAIL",
            f"Cannot resolve Yoke GitHub auth: {err}\n"
            f"Repair: {repair_command_hint(err, 'yoke')}",
        )
        return
    yoke_repo = yoke_auth.repo
    yoke_token = yoke_auth.token

    # Get items with github_issue + project with github_repo. Same-repo
    # rows (target_repo == resolved Yoke repo) cannot prove the
    # wrong-repo invariant — they are filtered below before any REST
    # call so the doctor scan stays O(distinct external projects)
    # instead of O(every linked Yoke row).
    rows = query_rows(
        conn,
        "SELECT i.id, i.github_issue, p.slug AS project, p.github_repo "
        "FROM items i "
        "JOIN projects p ON i.project_id = p.id "
        "WHERE i.github_issue IS NOT NULL AND i.github_issue <> '' "
        "AND p.github_repo IS NOT NULL AND p.github_repo <> ''",
    )

    issues: List[str] = []
    count = 0
    fixed_count = 0
    # Memoize per-project auth so each distinct project resolves once,
    # not once per item — the live DB at investigation time carried
    # ~1.8k linked Yoke rows where this collapses to a single resolve.
    project_auth_cache: dict[str, object] = {}
    # Backlog-only projects are out of scope: after the documented
    # sync-off -> repo-flip cutover their github_issue refs point at the
    # old repo as historical records, not wrong-repo violations
    # (docs/github-sync.md, "Old refs stay historical").
    sync_enabled_cache: dict[str, bool] = {}
    sync_disabled_notes: List[str] = []
    yoke_repo_norm = (yoke_repo or "").lower()

    for row in rows:
        item_id = row["id"]
        gh = row["github_issue"]
        project = row["project"]
        target_repo = row["github_repo"]
        num = gh.replace("#", "")

        enabled = sync_enabled_cache.get(project)
        if enabled is None:
            enabled = github_sync_enabled(project, conn=conn)
            sync_enabled_cache[project] = enabled
            if not enabled:
                sync_disabled_notes.append("- " + github_sync_disabled_notice(
                    project, "wrong-repo issue validation",
                ))
        if not enabled:
            continue

        # Same-repo Yoke rows cannot prove the wrong-repo invariant.
        if (target_repo or "").lower() == yoke_repo_norm:
            continue

        # Check if issue exists in target repo (project-scoped auth)
        cached = project_auth_cache.get(project)
        if cached is None:
            try:
                cached = resolve_project_github_auth(project, db_path=args.db_path)
            except ProjectGithubAuthError as err:
                # Cache the failure too so we do not retry per row.
                project_auth_cache[project] = err
                cached = err
            else:
                project_auth_cache[project] = cached
        if isinstance(cached, ProjectGithubAuthError):
            issues.append(
                f"- YOK-{item_id} (project={project}): "
                f"cannot resolve auth: {cached}\n"
                f"  Repair: {repair_command_hint(cached, project)}"
            )
            count += 1
            continue
        project_auth = cached
        r = issue_view_state(repo=target_repo, num=num, token=project_auth.token)
        state = r.stdout.strip() if r.returncode == 0 else ""

        if not state:
            # Not found in target repo: check Yoke repo (resolved dynamically)
            r2 = issue_view_state(repo=yoke_repo, num=num, token=yoke_token)
            default_state = r2.stdout.strip() if r2.returncode == 0 else ""

            count += 1
            if default_state:
                if args.fix:
                    if _migrate_issue(
                        conn, item_id, num, yoke_repo, target_repo,
                        project_token=project_auth.token,
                        yoke_token=yoke_token,
                    ):
                        fixed_count += 1
                        issues.append(
                            f"- YOK-{item_id} (project={project}): "
                            f"migrated #{num} from {yoke_repo} to {target_repo}"
                        )
                    else:
                        issues.append(
                            f"- YOK-{item_id} (project={project}): "
                            f"issue #{num} exists in {yoke_repo} but should be "
                            f"in {target_repo} (migration failed)"
                        )
                else:
                    issues.append(
                        f"- YOK-{item_id} (project={project}): "
                        f"issue #{num} exists in {yoke_repo} but should be in {target_repo}"
                    )
            else:
                issues.append(
                    f"- YOK-{item_id} (project={project}): "
                    f"issue #{num} not found in {target_repo} or {yoke_repo}"
                )

    notes_suffix = (
        "\n" + "\n".join(sync_disabled_notes) if sync_disabled_notes else ""
    )
    if issues:
        if args.fix and fixed_count > 0 and fixed_count == count:
            rec.record("HC-wrong-repo-issues", "Wrong-repo GitHub issues", "PASS",
                        f"Fixed: migrated {fixed_count} issue(s) to correct repo:\n"
                        + "\n".join(issues) + notes_suffix)
        else:
            rec.record("HC-wrong-repo-issues", "Wrong-repo GitHub issues", "WARN",
                        f"{count} item(s) with GitHub issues in the wrong repo:\n"
                        + "\n".join(issues) + notes_suffix)
    else:
        rec.record("HC-wrong-repo-issues", "Wrong-repo GitHub issues", "PASS",
                    notes_suffix.lstrip("\n"))


def _migrate_issue(
    conn,
    item_id: int,
    old_num: str,
    source_repo: str,
    target_repo: str,
    *,
    project_token: str,
    yoke_token: str,
) -> bool:
    """Migrate a GitHub issue from source to target repo. Returns True on success."""
    # 1. Fetch title/body/state/labels from old issue (Yoke-source auth)
    r = issue_view_full(repo=source_repo, num=old_num, token=yoke_token)
    if r.returncode != 0 or not r.stdout.strip():
        return False
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return False

    title = data.get("title", "")
    if not title:
        return False
    body = data.get("body", "")
    state = data.get("state", "")
    labels = [lab.get("name", "") for lab in data.get("labels", []) if lab.get("name")]
    comments = data.get("comments", [])

    # 2. Create new issue in target repo (target-project auth)
    r = issue_create(
        repo=target_repo, title=title, body=body or "", labels=labels,
        token=project_token,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return False

    new_url = r.stdout.strip()
    new_num_match = re.search(r"\d+$", new_url)
    if not new_num_match:
        return False
    new_num = new_num_match.group()

    # 3. Copy comments (best-effort; ignore individual failures)
    if comments:
        sorted_comments = sorted(comments, key=lambda c: c.get("createdAt", ""))
        for c in sorted_comments:
            author = c.get("author", {}).get("login", "unknown")
            date = c.get("createdAt", "")
            c_body = c.get("body", "")
            if c_body:
                comment_text = f"> *Migrated comment from @{author} ({date}):*\n\n{c_body}"
                issue_comment(
                    repo=target_repo, num=new_num, body=comment_text,
                    token=project_token,
                )

    # 4. Match state
    if state == "CLOSED":
        issue_close(repo=target_repo, num=new_num, token=project_token)

    # 5. Update DB
    p = _p(conn)
    conn.execute(
        f"UPDATE items SET github_issue = {p} WHERE id = {p}",
        (f"#{new_num}", item_id),
    )
    conn.commit()

    # 6. Close and delete old issue (best-effort cleanup; Yoke-source auth)
    close_text = (
        f"Migrated to {target_repo}#{new_num}. "
        f"This issue was in the wrong repo (YOK-{item_id})."
    )
    issue_comment(repo=source_repo, num=old_num, body=close_text, token=yoke_token)
    issue_close(repo=source_repo, num=old_num, token=yoke_token)
    issue_delete(repo=source_repo, num=old_num, token=yoke_token)

    return True
