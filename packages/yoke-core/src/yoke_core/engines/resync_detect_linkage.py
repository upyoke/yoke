"""Linkage and heavy-fetch stages for resync detection (bearer-token REST)."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

from yoke_contracts.public_ref import format_item_ref

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
from yoke_core.engines.resync_detect_models import (
    ITEM_REF_TITLE_PREFIX_RE,
    LocalOrphan,
    PairedItem,
)


def _project_out_of_scope(per_project_value: Dict) -> bool:
    """True when the project must be skipped for classification.

    Covers both sentinel shapes: unavailable GitHub state (engine warns) and
    sync-disabled (``github_sync_mode=disabled`` — the project's
    backlog is DB-only by design, so its items are never orphans).
    """
    return _project_unavailable(per_project_value) or _project_sync_disabled(
        per_project_value
    )


def stage1_linkage(
    db_path: str,  # noqa: ARG001 - retained compat token; reads now relay
    yoke_root: str,
    fetch_fn=None,
    *,
    project: str = "",
) -> Tuple[
    List[PairedItem],
    List[LocalOrphan],
    List[Tuple[int, str, str, str]],
    Dict[str, Dict[int, Dict]],
]:
    """Stage 1: build paired, local-orphan, and gh-orphan lists.

    Returns (paired, local_orphans, gh_orphans, gh_by_project).
    gh_orphans: list of (number, title, state, project)
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    # Build the project roster (backlog-derived slugs plus active repo
    # bindings) and per-project sync-disabled map server-side. Repository
    # authority does not come from the legacy projects projection; the
    # canonical resolver returns bound repo metadata and its matching bearer
    # token together. Disabled projects carry the sync-disabled sentinel
    # so no downstream stage classifies (or repairs) their items.
    roster_resp = call_dispatcher(
        function_id="resync.linkage_roster",
        target=TargetRef(kind="global"),
        payload={"project": project},
    )
    if not roster_resp.success:
        message = roster_resp.error.message if roster_resp.error else "unknown error"
        raise RuntimeError(f"resync linkage roster read failed: {message}")
    roster_data = roster_resp.result or {}
    fetch_projects = set(roster_data.get("fetch_projects", []))
    sync_disabled: Dict[str, str] = dict(roster_data.get("sync_disabled", {}))

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

    # Backlog + epic-task rows read after the fetch (relayed server-side so
    # the read runs over an https control plane as well as a local Postgres
    # connection). Backlog rows carry the ref-rendering columns
    # (public_item_prefix, project_sequence) alongside the internal id, so
    # the engine renders the true public ref without a second read. The
    # engine keeps the orphan/pairing classification below.
    rows_resp = call_dispatcher(
        function_id="resync.linkage_rows",
        target=TargetRef(kind="global"),
        payload={"project": project},
    )
    if not rows_resp.success:
        message = rows_resp.error.message if rows_resp.error else "unknown error"
        raise RuntimeError(f"resync linkage rows read failed: {message}")
    rows_data = rows_resp.result or {}
    backlog_rows = rows_data.get("backlog_rows", [])
    task_rows = rows_data.get("task_rows", [])

    paired: List[PairedItem] = []
    local_orphans: List[LocalOrphan] = []
    paired_gh_keys: set = set()
    backlog_dir = os.path.join(yoke_root, "backlog")

    for row in backlog_rows:
        item_id_num, gh_ref, item_project, ref_prefix, ref_sequence = row
        item_project = item_project or "yoke"
        item_pk = int(item_id_num)
        # The public display ref renders from prefix+sequence; identity
        # stays the internal ``items.id`` on the typed field.
        public_ref = format_item_ref(
            item_project,
            ref_prefix,
            ref_sequence,
            item_id=item_pk,
        )
        padded = str(item_pk).zfill(3)
        item_file = os.path.join(backlog_dir, f"{padded}.md")
        orphan = LocalOrphan(
            public_ref,
            item_file,
            "backlog",
            item_project,
            item_id=item_pk,
        )

        # GitHub state unavailable or sync disabled -- engine surfaces
        # the note; do NOT classify items here.
        if _project_out_of_scope(gh_by_project.get(item_project)):
            continue

        if not gh_ref or gh_ref == "null":
            local_orphans.append(orphan)
            continue

        gh_num_str = gh_ref.lstrip("#")
        try:
            gh_num = int(gh_num_str)
        except ValueError:
            local_orphans.append(orphan)
            continue

        project_issues = gh_by_project.get(item_project, {})
        if gh_num in project_issues:
            paired.append(
                PairedItem(
                    public_ref,
                    item_file,
                    gh_num,
                    "backlog",
                    item_project,
                    "",
                    item_id=item_pk,
                )
            )
            paired_gh_keys.add((item_project, gh_num))
        else:
            local_orphans.append(orphan)

    # Epic tasks (rows from the relayed read above; classification here).
    for slug, tnum, ttitle, gh_ref, project in task_rows:
        project = project or "yoke"
        task_ref = f"{slug}/task-{tnum:03d}"
        full_path = f"epic_tasks:{slug}/{tnum}"
        orphan = LocalOrphan(
            task_ref,
            full_path,
            "epic_task",
            project,
            epic_id=str(slug),
            task_num=int(tnum),
        )

        # GitHub state unavailable or sync disabled -- skip classification.
        if _project_out_of_scope(gh_by_project.get(project)):
            continue

        if not gh_ref or gh_ref == "null":
            local_orphans.append(orphan)
            continue

        gh_num_str = str(gh_ref).lstrip("#")
        try:
            gh_num = int(gh_num_str)
        except ValueError:
            local_orphans.append(orphan)
            continue

        project_issues = gh_by_project.get(project, {})
        if gh_num in project_issues:
            paired.append(
                PairedItem(
                    task_ref,
                    full_path,
                    gh_num,
                    "epic_task",
                    project,
                    "",
                    epic_id=str(slug),
                    task_num=int(tnum),
                )
            )
            paired_gh_keys.add((project, gh_num))
        else:
            local_orphans.append(orphan)

    # GitHub orphans (only titles carrying a public item-ref prefix).
    # Skip projects whose per-project value is the unavailable or
    # sync-disabled sentinel.
    gh_orphans: List[Tuple[int, str, str, str]] = []
    for proj, issues_map in sorted(gh_by_project.items()):
        if _project_out_of_scope(issues_map):
            continue
        for num, issue in sorted(issues_map.items()):
            if (proj, num) not in paired_gh_keys:
                title = issue.get("title", "")
                if ITEM_REF_TITLE_PREFIX_RE.match(title):
                    labels = [
                        label.get("name", "") for label in issue.get("labels", [])
                    ]
                    if "yoke:orphan" in labels:
                        continue
                    state = issue.get("state", "UNKNOWN")
                    gh_orphans.append((num, title, state, proj))

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
                exc,
                stage="graphql",
            )
            continue

        try:
            if graphql_fn is not None:
                heavy_by_project[project] = graphql_fn(
                    nums,
                    project=project,
                    auth=auth,
                )
            else:
                heavy_by_project[project] = _graphql_batch_fetch(
                    nums,
                    project=project,
                    auth=auth,
                )
        except ProjectGithubAuthError as exc:
            heavy_by_project[project] = _unavailable_sentinel(
                exc,
                stage="graphql",
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
                project,
                exc,
                stage="graphql",
            )

    return heavy_by_project
