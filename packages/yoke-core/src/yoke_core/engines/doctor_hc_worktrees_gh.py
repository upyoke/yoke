"""Worktree health checks — GitHub orphan and delegated-sync HCs.

Entry-point sibling for doctor's GitHub-cluster checks. Owns
``hc_orphaned_gh_issues``, ``hc_gh_orphan_detection``, and
``hc_delegated_sync`` directly, and re-exports the wrong-repo
migration HC and the project-scoped HCs from their dedicated
siblings so ``doctor.py`` keeps a single import surface for the
cluster.

GitHub auth + repo resolution flows through the canonical
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
surface. Test fixtures patch the canonical resolver directly.

HC functions: HC-orphaned-gh-issues, HC-gh-orphan-detection,
HC-delegated-sync (and re-exports of HC-wrong-repo-issues plus the
project-scoped GitHub checks).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import List

from yoke_core.domain import runtime_settings
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)


DOCTOR_RESYNC_RECURSIVE_TIMEOUT_CONFIG = "doctor_resync_recursive_timeout_seconds"
DEFAULT_DOCTOR_RESYNC_RECURSIVE_TIMEOUT_SECONDS = 120

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_hc_worktrees as _wt
import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _should_run_hc,
)
from yoke_core.engines.doctor_hc_worktrees import _DELEGATED_SYNC_HCS


from yoke_core.engines.doctor_hc_worktrees_gh_rest import (
    list_issues_by_labels_rest,
    search_issues_by_query_rest,
)

# Re-export wrong-repo migration HC so doctor.py imports a single sibling.
from yoke_core.engines.doctor_hc_worktrees_gh_repo import (  # noqa: F401
    hc_wrong_repo_issues,
)

# Re-export project-scoped HCs so doctor.py imports a single sibling.
from yoke_core.engines.doctor_hc_worktrees_gh_project import (  # noqa: F401
    hc_project_deploy_flows,
    hc_project_gh_secrets,
    hc_project_gh_auth,
    hc_project_health,
    hc_project_lookup,
    hc_project_repo_exists,
    hc_project_vps_reachable,
    hc_project_worktrees,
)


_DELEGATED_HC_LABELS = {
    "missing-gh-issues": "Missing GitHub issues",
    "orphan-epic-tasks": "Orphan epic tasks",
    "title-drift": "Title drift",
    "body-drift": "Body drift",
    "reverse-completeness": "Reverse completeness",
    "comment-sync": "Comment sync",
    "label-drift": "Label drift",
    "state-drift": "State drift",
    "frozen-label-drift": "Frozen label drift",
    "blocked-label-drift": "Blocked label drift",
    "task-label-drift": "Task label drift",
}


def hc_orphaned_gh_issues(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-gh-issues: Orphaned GitHub issues (per-project).

    Iterates every project with a configured ``github_repo`` and resolves
    auth through the canonical resolver.  Per-project ``ProjectGithubAuthError``
    is translated to a FAIL record with an operator-facing repair hint
    keyed off the failure code.

    When the host has no GitHub App auth configured for Yoke, SKIPs with the
    canonical reason (no FAIL, no host-``gh`` probe).
    """
    if not _wt._github_auth_configured("yoke", db_path=args.db_path):
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project="yoke"),
        )
        return

    # Build set of known github_issue numbers
    known_nums: set = set()
    rows = query_rows(
        conn,
        "SELECT id, github_issue FROM items "
        "WHERE github_issue IS NOT NULL AND github_issue <> ''",
    )
    for row in rows:
        gh = row["github_issue"]
        if gh and gh != "null":
            known_nums.add(gh.replace("#", ""))

    # Iterate every project with a configured github_repo. Backlog-only
    # projects are out of scope: their backlog is DB-only by design, so
    # their repo's issue tracker is never expected to mirror the backlog
    # (docs/github-sync.md, "Backlog-only semantics").
    all_issues: set = set()
    auth_failures: List[str] = []
    sync_disabled_notes: List[str] = []

    if _base._table_exists(conn, "projects"):
        proj_rows = query_rows(
            conn,
            "SELECT slug, COALESCE(github_repo, '') as github_repo FROM projects "
            "WHERE github_repo IS NOT NULL AND github_repo <> ''",
        )
        for prow in proj_rows:
            project = prow["slug"]
            if not github_sync_enabled(project, conn=conn):
                sync_disabled_notes.append("- " + github_sync_disabled_notice(
                    project, "orphaned-issue scan",
                ))
                continue
            try:
                auth = resolve_project_github_auth(project, db_path=args.db_path)
            except ProjectGithubAuthError as err:
                auth_failures.append(
                    f"- project '{project}': {err}\n"
                    f"  Repair: {repair_command_hint(err, project)}"
                )
                continue
            for label in ("type:epic", "type:issue"):
                parts = auth.repo.split("/", 1)
                if len(parts) != 2:
                    continue
                owner, name = parts
                r = list_issues_by_labels_rest(
                    owner=owner, name=name, token=auth.token,
                    labels=[label], state="open",
                )
                if r.returncode == 0:
                    for num in r.stdout.strip().splitlines():
                        if num.strip():
                            all_issues.add(num.strip())

    if auth_failures:
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "FAIL",
            "Cannot resolve project GitHub auth:\n" + "\n".join(auth_failures),
        )
        return

    issues: List[str] = []
    for num in sorted(all_issues, key=lambda x: int(x) if x.isdigit() else 0):
        if num not in known_nums:
            issues.append(f"- GitHub issue #{num} has Yoke labels but no matching backlog item")

    if issues:
        rec.record("HC-orphaned-gh-issues", "Orphaned GitHub issues", "WARN",
                    "\n".join(issues + sync_disabled_notes))
    else:
        rec.record("HC-orphaned-gh-issues", "Orphaned GitHub issues", "PASS",
                    "\n".join(sync_disabled_notes))



def hc_gh_orphan_detection(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-gh-orphan-detection: GitHub orphan detection (per-project).

    Iterates every project with a configured ``github_repo`` and resolves
    auth through the canonical resolver.  Per-project ``ProjectGithubAuthError``
    is translated to a FAIL record with an operator-facing repair hint.

    SKIPs with the canonical reason when no GitHub App auth is configured for Yoke.
    """
    if not _wt._github_auth_configured("yoke", db_path=args.db_path):
        rec.record(
            "HC-gh-orphan-detection", "GitHub orphan detection", "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project="yoke"),
        )
        return

    # Build set of all linked issue numbers (items + epic_tasks)
    known_nums: set = set()
    rows = query_rows(
        conn,
        "SELECT github_issue FROM items "
        "WHERE github_issue IS NOT NULL AND github_issue <> ''",
    )
    for row in rows:
        gh = row["github_issue"]
        if gh and gh != "null":
            known_nums.add(gh.replace("#", ""))

    if _base._table_exists(conn, "epic_tasks") and _base._column_exists(conn, "epic_tasks", "github_issue"):
        task_rows = query_rows(
            conn,
            "SELECT github_issue FROM epic_tasks "
            "WHERE github_issue IS NOT NULL AND github_issue <> ''",
        )
        for row in task_rows:
            gh = row["github_issue"]
            if gh and gh != "null":
                known_nums.add(gh.replace("#", ""))

    # Iterate every project with a configured github_repo. Backlog-only
    # projects are out of scope: their backlog never mirrors to their
    # repo's issue tracker, so a [YOK-]-prefixed issue there is not a
    # sync orphan (docs/github-sync.md, "Backlog-only semantics").
    all_gh_issues: List[dict] = []
    auth_failures: List[str] = []
    sync_disabled_notes: List[str] = []

    if _base._table_exists(conn, "projects"):
        proj_rows = query_rows(
            conn,
            "SELECT slug, COALESCE(github_repo, '') as github_repo FROM projects "
            "WHERE github_repo IS NOT NULL AND github_repo <> ''",
        )
        for prow in proj_rows:
            project = prow["slug"]
            if not github_sync_enabled(project, conn=conn):
                sync_disabled_notes.append("- " + github_sync_disabled_notice(
                    project, "orphan detection",
                ))
                continue
            try:
                auth = resolve_project_github_auth(project, db_path=args.db_path)
            except ProjectGithubAuthError as err:
                auth_failures.append(
                    f"- project '{project}': {err}\n"
                    f"  Repair: {repair_command_hint(err, project)}"
                )
                continue
            parts = auth.repo.split("/", 1)
            if len(parts) != 2:
                continue
            owner, name = parts
            r = search_issues_by_query_rest(
                owner=owner, name=name, token=auth.token,
                search="[YOK-", limit=500,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    all_gh_issues.extend(json.loads(r.stdout))
                except json.JSONDecodeError:
                    pass

    if auth_failures:
        rec.record(
            "HC-gh-orphan-detection", "GitHub orphan detection", "FAIL",
            "Cannot resolve project GitHub auth:\n" + "\n".join(auth_failures),
        )
        return

    # Deduplicate and check
    seen: set = set()
    issues: List[str] = []
    for iss in all_gh_issues:
        num = str(iss.get("number", ""))
        if num in seen or num in known_nums:
            continue
        seen.add(num)
        title = iss.get("title", "")
        state = iss.get("state", "")
        issues.append(f"- #{num} ({state}): {title}")

    notes_suffix = (
        "\n" + "\n".join(sync_disabled_notes) if sync_disabled_notes else ""
    )
    if issues:
        count = len(issues)
        detail = (
            f"{count} GitHub issue(s) with [YOK-] prefix not linked from "
            f"any backlog item or epic task:\n" + "\n".join(issues)
        )
        rec.record("HC-gh-orphan-detection", "GitHub orphan detection", "WARN",
                    detail + notes_suffix)
    else:
        rec.record("HC-gh-orphan-detection", "GitHub orphan detection", "PASS",
                    notes_suffix.lstrip("\n"))



def hc_delegated_sync(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Delegated sync HCs: call resync engine in doctor-format mode."""
    # Determine which delegated HCs are requested
    requested = set()
    for slug in _DELEGATED_SYNC_HCS:
        if _should_run_hc(slug, args):
            requested.add(slug)
    if not requested and _should_run_hc("delegated-sync", args):
        requested.update(_DELEGATED_SYNC_HCS)

    if not requested:
        return

    # Try Python resync engine first
    flags = ["--fix" if args.fix else "--detect-only", "--doctor-format"]
    if args.db_path:
        flags.extend(["--db-path", args.db_path])

    timeout_s = runtime_settings.get_seconds(
        DOCTOR_RESYNC_RECURSIVE_TIMEOUT_CONFIG,
        DEFAULT_DOCTOR_RESYNC_RECURSIVE_TIMEOUT_SECONDS,
    )
    r = _base._run(
        [sys.executable, "-m", "yoke_core.engines.resync"] + flags,
        timeout=timeout_s,
    )

    if r.returncode == 124:
        detail = (
            f"resync engine timed out after {timeout_s}s; delegated sync HCs "
            "were skipped to keep Doctor bounded. Run "
            "`python3 -m yoke_core.engines.resync --detect-only "
            "--doctor-format` directly for full sync diagnostics."
        )
        if r.stderr.strip():
            detail += f" Subprocess detail: {r.stderr.strip()}"
        for slug in requested:
            label = _DELEGATED_HC_LABELS.get(slug, slug)
            rec.record(f"HC-{slug}", label, "WARN", detail)
        return

    if r.returncode in (0, 1) and r.stdout.strip():
        # Parse pipe-delimited output
        seen_slugs: set = set()
        for line in r.stdout.strip().splitlines():
            parts = line.split("|", 3)
            if len(parts) < 4:
                continue
            hc_id, hc_label, hc_status, hc_detail = parts
            hc_id = hc_id.strip()
            slug = hc_id.replace("HC-", "")
            if slug in requested:
                seen_slugs.add(slug)
                rec.record(hc_id, hc_label.strip(), hc_status.strip(),
                           hc_detail.strip())

        # Emit WARN for any requested but unseen HCs
        for slug in requested:
            if slug not in seen_slugs:
                label = _DELEGATED_HC_LABELS.get(slug, slug)
                rec.record(f"HC-{slug}", label, "WARN",
                           "resync engine did not report this HC")
    else:
        # Fallback: resync engine not available or failed
        detail = "resync engine not available or produced no doctor-format output"
        if r.stderr.strip():
            detail += f"; stderr: {r.stderr.strip()}"
        for slug in requested:
            label = _DELEGATED_HC_LABELS.get(slug, slug)
            rec.record(f"HC-{slug}", label, "WARN", detail)
