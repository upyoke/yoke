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

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_contracts.doctor_budget import CHECK_BUDGET_S, remaining_seconds
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)
import yoke_core.engines.doctor_hc_worktrees as _wt
import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON
from yoke_core.engines.doctor_hc_worktrees_gh_repo_rest import (
    issue_close,
    issue_comment,
    issue_create,
    issue_delete,
    issue_view_full,
    repository_issue_states,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_wrong_repo_issues(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Check verified repository bindings using one inventory per repository."""
    if not _wt._github_auth_configured("yoke", db_path=args.db_path):
        rec.record(
            "HC-wrong-repo-issues",
            "Wrong-repo GitHub issues",
            "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project="yoke"),
        )
        return
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-wrong-repo-issues", "Wrong-repo GitHub issues", "PASS", "")
        return
    permissions = (
        GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
        if args.fix
        else GITHUB_ISSUES_READ_PERMISSION_LEVELS
    )
    try:
        source_auth = resolve_project_github_auth(
            "yoke",
            db_path=args.db_path,
            conn=conn,
            required_permissions=permissions,
        )
    except ProjectGithubAuthError as err:
        rec.record(
            "HC-wrong-repo-issues",
            "Wrong-repo GitHub issues",
            "FAIL",
            f"Cannot resolve Yoke GitHub auth: {err}\n"
            f"Repair: {repair_command_hint(err, 'yoke')}",
        )
        return

    rows = query_rows(
        conn,
        "SELECT i.id, i.github_issue, p.slug AS project FROM items i "
        "JOIN projects p ON i.project_id = p.id "
        "WHERE i.github_issue IS NOT NULL AND i.github_issue <> ''",
    )
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["project"], []).append(row)
    findings: list[tuple[int, str]] = []
    notes: list[str] = []
    inventories: dict[str, dict[str, str]] = {}
    fixed_count = 0
    incomplete = False

    def inventory(auth):
        key = auth.repo.lower()
        if key not in inventories:
            try:
                inventories[key] = repository_issue_states(
                    repo=auth.repo, token=auth.token
                )
            except RestTransportError as err:
                raise RestTransportError(f"{auth.repo}: {err}") from None
        return inventories[key]

    for project, project_rows in grouped.items():
        remaining_seconds(CHECK_BUDGET_S)
        if not github_sync_enabled(project, conn=conn):
            notes.append(
                "- "
                + github_sync_disabled_notice(project, "wrong-repo issue validation")
            )
            continue
        try:
            auth = (
                source_auth
                if project == "yoke"
                else resolve_project_github_auth(
                    project,
                    db_path=args.db_path,
                    conn=conn,
                    required_permissions=permissions,
                )
            )
        except ProjectGithubAuthError as err:
            findings.extend(
                (
                    int(row["id"]),
                    f"(project={project}): cannot resolve auth: {err}\n"
                    f"  Repair: {repair_command_hint(err, project)}",
                )
                for row in project_rows
            )
            incomplete = True
            continue
        # Same-repository rows never enter reference rendering or HTTP inventory.
        if auth.repo.lower() == source_auth.repo.lower():
            continue
        try:
            target_states = inventory(auth)
            missing = [
                row
                for row in project_rows
                if row["github_issue"].replace("#", "") not in target_states
            ]
            if not missing:
                continue
            source_states = inventory(source_auth)
        except RestTransportError as err:
            incomplete = True
            notes.append(
                f"repository_issue_inventory_failed: {auth.repo}: {err}. "
                "Evidence incomplete. Recovery: retry --only wrong-repo-issues "
                "after GitHub access recovers."
            )
            continue
        for row in missing:
            remaining_seconds(CHECK_BUDGET_S)
            item_id = int(row["id"])
            num = row["github_issue"].replace("#", "")
            if num not in source_states:
                message = f"issue #{num} not found in {auth.repo} or {source_auth.repo}"
            elif args.fix and _migrate_issue(
                conn,
                item_id,
                num,
                source_auth.repo,
                auth.repo,
                project_token=auth.token,
                yoke_token=source_auth.token,
            ):
                fixed_count += 1
                message = f"migrated #{num} from {source_auth.repo} to {auth.repo}"
            else:
                message = f"issue #{num} exists in {source_auth.repo} but should be in {auth.repo}"
                if args.fix:
                    message += " (migration failed)"
            findings.append((item_id, f"(project={project}): {message}"))

    refs = render_item_ref_lookup(conn, (item_id for item_id, _ in findings))
    details = [f"- {refs(item_id)} {message}" for item_id, message in findings]
    if incomplete:
        verdict = "FAIL"
        heading = "Wrong-repo issue validation incomplete."
    elif findings and args.fix and fixed_count == len(findings):
        verdict = "PASS"
        heading = f"Fixed: migrated {fixed_count} issue(s) to correct repo:"
    elif findings:
        verdict = "WARN"
        heading = f"{len(findings)} item(s) with GitHub issues in the wrong repo:"
    else:
        verdict, heading = "PASS", ""
    rec.record(
        "HC-wrong-repo-issues",
        "Wrong-repo GitHub issues",
        verdict,
        "\n".join(part for part in [heading, *details, *notes] if part),
    )


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
        repo=target_repo,
        title=title,
        body=body or "",
        labels=labels,
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
                comment_text = (
                    f"> *Migrated comment from @{author} ({date}):*\n\n{c_body}"
                )
                issue_comment(
                    repo=target_repo,
                    num=new_num,
                    body=comment_text,
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
        f"This issue was in the wrong repo ({render_item_ref(conn, int(item_id))})."
    )
    issue_comment(repo=source_repo, num=old_num, body=close_text, token=yoke_token)
    issue_close(repo=source_repo, num=old_num, token=yoke_token)
    issue_delete(repo=source_repo, num=old_num, token=yoke_token)

    return True
