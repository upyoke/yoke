"""Linkage and heavy-fetch stages for resync detection (bearer-token REST)."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import RestAuthError, RestTransportError
from yoke_core.domain.project_github_auth import (
    InvalidToken,
    ProjectGithubAuthError,
    TransportFailure,
    resolve_project_github_auth,
)
from yoke_core.engines.resync_detect_fetch import (
    _fetch_gh_issues_per_project,
    _auth_failure_sentinel,
    _project_unavailable,
    _project_sync_disabled,
    _sync_disabled_sentinel,
    _transport_failure_sentinel,
    _unavailable_sentinel,
)
from yoke_core.engines.resync_detect_fetch import (  # noqa: F401 — re-export
    _graphql_batch_fetch,
)
from yoke_core.engines.resync_detect_models import PairedItem


def _project_out_of_scope(per_project_value: Dict) -> bool:
    """True when the project must be skipped for classification.

    Covers both sentinel shapes: unavailable GitHub state (engine warns) and
    sync-disabled (``github_sync_mode=backlog_only`` — the project's
    backlog is DB-only by design, so its items are never orphans).
    """
    return (
        _project_unavailable(per_project_value)
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
    from yoke_core.domain.schema_common import _table_exists as _schema_table_exists

    conn = connect(db_path)

    def _table_exists(table_name: str) -> bool:
        return _schema_table_exists(conn, table_name)

    # Build the project roster from work represented in the backlog plus
    # active bindings (which may have GitHub-only orphans). Repository
    # authority does not come from the legacy projects projection; the
    # canonical resolver returns bound repo metadata and its matching bearer
    # token together.
    project_roster: set[str] = {"yoke"}
    try:
        rows = conn.execute(
            "SELECT DISTINCT COALESCE(p.slug, 'yoke') "
            "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
        ).fetchall()
        for row in rows:
            project_roster.add(row[0])
    except db_backend.operational_error_types(conn):
        conn.rollback()
        pass
    if _table_exists("project_github_repo_bindings"):
        try:
            rows = conn.execute(
                "SELECT DISTINCT p.slug "
                "FROM project_github_repo_bindings b "
                "JOIN projects p ON p.id = b.project_id "
                "WHERE b.status = 'active'"
            ).fetchall()
            for row in rows:
                project_roster.add(row[0])
        except db_backend.operational_error_types(conn):
            conn.rollback()

    # Per-project GitHub sync switch: backlog-only projects are excluded
    # from the fetch entirely and carry the sync-disabled sentinel so no
    # downstream stage classifies (or repairs) their items.
    from yoke_core.domain.projects_github_sync_mode import (
        GITHUB_SYNC_ENABLED,
        resolve_github_sync_mode,
    )

    sync_disabled: Dict[str, str] = {}
    for slug in project_roster:
        mode = resolve_github_sync_mode(slug, conn=conn)
        if mode != GITHUB_SYNC_ENABLED:
            sync_disabled[slug] = mode
    fetch_projects = project_roster.difference(sync_disabled)

    # Fetch GitHub issues -- use injected fetch_fn (allows mock patching in tests)
    if fetch_fn is not None:
        gh_by_project = fetch_fn(fetch_projects)
    else:
        gh_by_project = _fetch_gh_issues_per_project(fetch_projects)
    for slug in fetch_projects:
        if slug not in gh_by_project:
            gh_by_project[slug] = _unavailable_sentinel(
                TransportFailure(
                    slug,
                    f"GitHub issues fetch returned no state for project '{slug}'",
                ),
                stage="issues",
            )
    for slug, mode in sync_disabled.items():
        gh_by_project[slug] = _sync_disabled_sentinel(mode)

    # Build backlog map from DB
    projects_table_exists = _table_exists("projects")
    try:
        if projects_table_exists:
            backlog_rows = conn.execute(
                "SELECT i.id, COALESCE(i.github_issue, ''), COALESCE(p.slug, 'yoke') "
                "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
            ).fetchall()
        else:
            backlog_rows = conn.execute(
                "SELECT id, COALESCE(github_issue, ''), 'yoke' FROM items"
            ).fetchall()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        backlog_rows = conn.execute(
            "SELECT id, COALESCE(github_issue, ''), 'yoke' FROM items"
        ).fetchall()

    paired: List[PairedItem] = []
    local_orphans: List[Tuple[str, str, str, str]] = []
    paired_gh_keys: set = set()
    backlog_dir = os.path.join(yoke_root, "backlog")

    for row in backlog_rows:
        item_id_num, gh_ref, item_project = row
        item_project = item_project or "yoke"
        item_id = f"YOK-{item_id_num}"
        padded = str(item_id_num).zfill(3)
        item_file = os.path.join(backlog_dir, f"{padded}.md")

        # GitHub state unavailable or sync disabled -- engine surfaces
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
            paired.append(PairedItem(item_id, item_file, gh_num, "backlog", item_project, ""))
            paired_gh_keys.add((item_project, gh_num))
        else:
            local_orphans.append((item_id, item_file, "backlog", item_project))

    # Epic tasks
    try:
        if projects_table_exists:
            task_rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "COALESCE(p.slug, 'yoke') "
                "FROM epic_tasks et "
                "LEFT JOIN items i ON CAST(et.epic_id AS TEXT) = CAST(i.id AS TEXT) "
                "LEFT JOIN projects p ON i.project_id = p.id "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
        else:
            task_rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "'yoke' as project "
                "FROM epic_tasks et "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
        for slug, tnum, ttitle, gh_ref, project in task_rows:
            project = project or "yoke"
            task_id = f"{slug}/task-{tnum:03d}"
            full_path = f"epic_tasks:{slug}/{tnum}"

            # GitHub state unavailable or sync disabled -- skip classification.
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
                paired.append(PairedItem(task_id, full_path, gh_num, "epic_task", project, ""))
                paired_gh_keys.add((project, gh_num))
            else:
                local_orphans.append((task_id, full_path, "epic_task", project))
    except db_backend.operational_error_types(conn):
        conn.rollback()
        pass

    # GitHub orphans (only [YOK- prefixed titles). Skip projects whose
    # per-project value is the unavailable or sync-disabled sentinel.
    gh_orphans: List[Tuple[int, str, str, str]] = []
    sun_prefix_re = re.compile(r"^\[YOK-\d+\]")
    for proj, issues_map in sorted(gh_by_project.items()):
        if _project_out_of_scope(issues_map):
            continue
        for num, issue in sorted(issues_map.items()):
            if (proj, num) not in paired_gh_keys:
                title = issue.get("title", "")
                if sun_prefix_re.match(title):
                    labels = [
                        label.get("name", "") for label in issue.get("labels", [])
                    ]
                    if "yoke:orphan" in labels:
                        continue
                    state = issue.get("state", "UNKNOWN")
                    gh_orphans.append((num, title, state, proj))

    conn.close()
    return paired, local_orphans, gh_orphans, gh_by_project


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

    heavy_by_project: Dict[str, Dict[int, Dict]] = {}

    for proj, nums in nums_by_project.items():
        project = proj or "yoke"
        light_state = gh_by_project.get(project)
        if _project_out_of_scope(light_state):
            continue

        try:
            auth = resolve_project_github_auth(
                project,
                required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
            )
        except ProjectGithubAuthError as exc:
            heavy_by_project[project] = _unavailable_sentinel(
                exc, stage="graphql",
            )
            continue

        try:
            if graphql_fn is not None:
                heavy_by_project[project] = graphql_fn(
                    nums, project=project, auth=auth,
                )
            else:
                heavy_by_project[project] = _graphql_batch_fetch(
                    nums, project=project, auth=auth,
                )
        except ProjectGithubAuthError as exc:
            heavy_by_project[project] = _unavailable_sentinel(
                exc, stage="graphql",
            )
        except RestAuthError as exc:
            heavy_by_project[project] = _auth_failure_sentinel(
                InvalidToken(
                    project,
                    f"GraphQL rejected token for project '{project}': {exc}",
                ),
                stage="graphql",
            )
        except RestTransportError as exc:
            heavy_by_project[project] = _transport_failure_sentinel(
                project, exc, stage="graphql",
            )

    return heavy_by_project
