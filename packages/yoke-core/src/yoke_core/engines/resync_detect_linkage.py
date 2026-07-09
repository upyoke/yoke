"""Linkage and heavy-fetch stages for resync detection (bearer-token REST)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.engines.resync_detect_fetch import (
    _fetch_gh_issues_per_project,
    _project_sync_disabled,
    _sync_disabled_sentinel,
)
from yoke_core.engines.resync_detect_fetch import (  # noqa: F401 — re-export
    _graphql_batch_fetch,
)
from yoke_core.engines.resync_detect_models import PairedItem


def _project_failed_auth(per_project_value: Dict) -> bool:
    """Return True when ``per_project_value`` carries the auth-failure sentinel.

    ``_fetch_gh_issues_per_project`` substitutes the per-project value with a
    sentinel dict ``{"_auth_error": ..., "_repair_hint": ...}`` when the
    canonical resolver raises. Downstream consumers MUST treat such projects as
    "skip — do not classify, do not manufacture orphans".
    """
    return isinstance(per_project_value, dict) and "_auth_error" in per_project_value


def _project_out_of_scope(per_project_value: Dict) -> bool:
    """True when the project must be skipped for classification.

    Covers both sentinel shapes: auth failure (engine warns) and
    sync-disabled (``github_sync_mode=backlog_only`` — the project's
    backlog is DB-only by design, so its items are never orphans).
    """
    return (
        _project_failed_auth(per_project_value)
        or _project_sync_disabled(per_project_value)
    )

def stage1_linkage(
    db_path: str,
    yoke_root: str,
    fetch_fn=None,
) -> Tuple[List[PairedItem], List[Tuple[str, str, str, str]], List[Tuple[int, str, str, str]], Dict[str, Dict[int, Dict]]]:
    """Stage 1: build paired, local-orphan, and gh-orphan lists.

    Returns (paired, local_orphans, gh_orphans, gh_by_project).
    local_orphans: list of (id, file, type, project)
    gh_orphans: list of (number, title, state, project)
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.schema_common import (
        _column_exists as _schema_column_exists,
        _table_exists as _schema_table_exists,
    )

    conn = connect(db_path)

    def _table_exists(table_name: str) -> bool:
        return _schema_table_exists(conn, table_name)

    def _column_exists(table_name: str, column_name: str) -> bool:
        return _schema_column_exists(conn, table_name, column_name)

    # Build project-repo map
    project_map: Dict[str, str] = {"yoke": ""}
    try:
        rows = conn.execute(
            "SELECT slug, COALESCE(github_repo, '') FROM projects"
        ).fetchall()
        for pid, repo in rows:
            project_map[pid] = repo
    except db_backend.operational_error_types(conn):
        conn.rollback()
        pass

    # Per-project GitHub sync switch: backlog-only projects are excluded
    # from the fetch entirely and carry the sync-disabled sentinel so no
    # downstream stage classifies (or repairs) their items.
    from yoke_core.domain.projects_github_sync_mode import (
        GITHUB_SYNC_ENABLED,
        resolve_github_sync_mode,
    )

    sync_disabled: Dict[str, str] = {}
    for slug in list(project_map):
        mode = resolve_github_sync_mode(slug, conn=conn)
        if mode != GITHUB_SYNC_ENABLED:
            sync_disabled[slug] = mode
    fetch_map = {
        slug: repo for slug, repo in project_map.items()
        if slug not in sync_disabled
    }

    # Fetch GitHub issues -- use injected fetch_fn (allows mock patching in tests)
    if fetch_fn is not None:
        gh_by_project = fetch_fn(fetch_map)
    else:
        gh_by_project = _fetch_gh_issues_per_project(fetch_map)
    for slug, mode in sync_disabled.items():
        gh_by_project[slug] = _sync_disabled_sentinel(mode)

    # Build backlog map from DB
    projects_table_exists = _table_exists("projects")
    try:
        if projects_table_exists:
            backlog_rows = conn.execute(
                "SELECT i.id, COALESCE(i.github_issue, ''), COALESCE(p.slug, 'yoke'), "
                "COALESCE(p.github_repo, '') "
                "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
            ).fetchall()
        else:
            backlog_rows = conn.execute(
                "SELECT id, COALESCE(github_issue, ''), 'yoke', '' FROM items"
            ).fetchall()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        backlog_rows = conn.execute(
            "SELECT id, COALESCE(github_issue, ''), 'yoke', '' FROM items"
        ).fetchall()

    paired: List[PairedItem] = []
    local_orphans: List[Tuple[str, str, str, str]] = []
    paired_gh_keys: set = set()
    backlog_dir = os.path.join(yoke_root, "backlog")

    for row in backlog_rows:
        item_id_num, gh_ref, item_project, item_repo = row
        item_project = item_project or "yoke"
        item_id = f"YOK-{item_id_num}"
        padded = str(item_id_num).zfill(3)
        item_file = os.path.join(backlog_dir, f"{padded}.md")

        # Auth failed or sync disabled for this project -- engine surfaces
        # the note; do NOT classify items here.
        if _project_out_of_scope(gh_by_project.get(item_project)):
            continue

        if not gh_ref or gh_ref == "null":
            local_orphans.append((item_id, item_file, "backlog", item_project))
            continue

        gh_num_str = gh_ref.lstrip("#")
        try:
            gh_num = int(gh_num_str)
        except ValueError:
            local_orphans.append((item_id, item_file, "backlog", item_project))
            continue

        project_issues = gh_by_project.get(item_project, {})
        if gh_num in project_issues:
            paired.append(PairedItem(item_id, item_file, gh_num, "backlog", item_project, item_repo))
            paired_gh_keys.add((item_project, gh_num))
        else:
            local_orphans.append((item_id, item_file, "backlog", item_project))

    # Epic tasks
    try:
        if projects_table_exists:
            task_rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "COALESCE(p.slug, 'yoke'), COALESCE(p.github_repo, '') as github_repo "
                "FROM epic_tasks et "
                "LEFT JOIN items i ON CAST(et.epic_id AS TEXT) = CAST(i.id AS TEXT) "
                "LEFT JOIN projects p ON i.project_id = p.id "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
        else:
            task_rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "'yoke' as project, '' as github_repo "
                "FROM epic_tasks et "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
        for slug, tnum, ttitle, gh_ref, project, repo in task_rows:
            project = project or "yoke"
            task_id = f"{slug}/task-{tnum:03d}"
            full_path = f"epic_tasks:{slug}/{tnum}"

            # Auth failed or sync disabled -- skip classification.
            if _project_out_of_scope(gh_by_project.get(project)):
                continue

            if not gh_ref or gh_ref == "null":
                local_orphans.append((task_id, full_path, "epic_task", project))
                continue

            gh_num_str = str(gh_ref).lstrip("#")
            try:
                gh_num = int(gh_num_str)
            except ValueError:
                local_orphans.append((task_id, full_path, "epic_task", project))
                continue

            project_issues = gh_by_project.get(project, {})
            if gh_num in project_issues:
                paired.append(PairedItem(task_id, full_path, gh_num, "epic_task", project, repo or ""))
                paired_gh_keys.add((project, gh_num))
            else:
                local_orphans.append((task_id, full_path, "epic_task", project))
    except db_backend.operational_error_types(conn):
        conn.rollback()
        pass

    # GitHub orphans (only [YOK- prefixed titles). Skip projects whose
    # per-project value is the auth-failure or sync-disabled sentinel.
    gh_orphans: List[Tuple[int, str, str, str]] = []
    sun_prefix_re = re.compile(r"^\[YOK-\d+\]")
    for proj, issues_map in sorted(gh_by_project.items()):
        if _project_out_of_scope(issues_map):
            continue
        for num, issue in sorted(issues_map.items()):
            if (proj, num) not in paired_gh_keys:
                title = issue.get("title", "")
                if sun_prefix_re.match(title):
                    labels = [l.get("name", "") for l in issue.get("labels", [])]
                    if "yoke:orphan" in labels:
                        continue
                    state = issue.get("state", "UNKNOWN")
                    gh_orphans.append((num, title, state, proj))

    conn.close()
    return paired, local_orphans, gh_orphans, gh_by_project


def _resolve_default_repo_nwo() -> str:
    """Return the Yoke project's repo NWO; empty string when auth fails."""
    try:
        auth = resolve_project_github_auth("yoke")
    except ProjectGithubAuthError:
        return ""
    return auth.repo


def stage1_5_heavy_fetch(
    paired: List[PairedItem],
    gh_by_project: Dict[str, Dict[int, Dict]],
    graphql_fn=None,
) -> Dict[str, Dict[int, Dict]]:
    """Stage 1.5: heavy fetch for paired items (backlog + epic_task)."""
    nums_by_project: Dict[str, List[int]] = {}
    for item in paired:
        proj = item.project or "yoke"
        nums_by_project.setdefault(proj, []).append(item.gh_num)

    if not nums_by_project:
        return {}

    default_repo_nwo = _resolve_default_repo_nwo()

    heavy_by_project: Dict[str, Dict[int, Dict]] = {}

    for proj, nums in nums_by_project.items():
        if proj == "yoke" or not proj:
            repo_nwo = default_repo_nwo
        else:
            repo_nwo = ""
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "yoke_core.domain.projects",
                     "get", proj, "github_repo"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    repo_nwo = result.stdout.strip()
            except Exception:
                pass

        if not repo_nwo:
            continue

        parts = repo_nwo.split("/", 1)
        if len(parts) != 2:
            continue
        owner, repo_name = parts

        # Per-project auth failures inside the heavy fetch are caught here so
        # one project's misconfiguration cannot abort the entire stage.
        try:
            if graphql_fn is not None:
                heavy_by_project[proj] = graphql_fn(
                    nums, owner, repo_name, project=proj,
                )
            else:
                heavy_by_project[proj] = _graphql_batch_fetch(
                    nums, owner, repo_name, project=proj,
                )
        except ProjectGithubAuthError:
            continue
        except RestTransportError:
            continue

    return heavy_by_project
