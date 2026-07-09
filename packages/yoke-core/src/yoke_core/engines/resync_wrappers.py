"""Patch-friendly wrappers for resync detection and repair stages (bearer-token REST).

Exception propagation contract: these wrappers do not catch
:class:`yoke_core.domain.project_github_auth.ProjectGithubAuthError` or
:class:`yoke_core.domain.gh_rest_transport.RestTransportError`. Both
propagate to the engine boundary in ``resync.main`` for typed-error +
repair-hint rendering. Detect-stage wrappers consume the REST transport
directly; repair-stage wrappers route through the typed
:mod:`yoke_core.domain.github_rest` surface (no argv plumbing).
"""

from __future__ import annotations


def _parent():
    from yoke_core.engines import resync as _resync
    return _resync

def _fetch_gh_issues_per_project(project_map):
    """Wrapper: fetch GitHub issues via REST."""
    from yoke_core.engines.resync_detect import _fetch_gh_issues_per_project as _fn
    return _fn(project_map)


def _graphql_batch_fetch(nums, owner, repo, project="yoke", batch_size=50):
    """Wrapper: GraphQL batch fetch via REST."""
    from yoke_core.engines.resync_detect import _graphql_batch_fetch as _fn
    return _fn(nums, owner, repo, project=project, batch_size=batch_size)


def stage1_linkage(
    db_path: str,
    yoke_root: str,
):
    """Stage 1: build paired, local-orphan, and gh-orphan lists."""
    from yoke_core.engines.resync_detect import stage1_linkage as _stage1
    import yoke_core.engines.resync as _self

    # Pass a fetch_fn that routes through resync._fetch_gh_issues_per_project
    # so that test patches of resync._fetch_gh_issues_per_project are honoured.
    def _fetch_fn(project_map):
        return _self._fetch_gh_issues_per_project(project_map)

    return _stage1(db_path, yoke_root, fetch_fn=_fetch_fn)


def stage1_5_heavy_fetch(paired, gh_by_project):
    """Stage 1.5: heavy fetch for paired backlog items (body + comments)."""
    from yoke_core.engines.resync_detect import stage1_5_heavy_fetch as _stage1_5
    import yoke_core.engines.resync as _self

    # Pass graphql_fn so that test patches of resync._graphql_batch_fetch are honoured.
    def _graphql_fn(nums, owner, repo, project="yoke"):
        return _self._graphql_batch_fetch(nums, owner, repo, project=project)

    return _stage1_5(paired, gh_by_project, graphql_fn=_graphql_fn)


def _repair_local_orphan_backlog(item_id, project):
    from yoke_core.engines.resync_apply import _repair_local_orphan_backlog as _fn
    return _fn(item_id, project, call_domain_sync_fn=_parent()._call_domain_sync)


def _repair_local_orphan_epic_task(item_id, project, db_path):
    from yoke_core.engines.resync_apply import _repair_local_orphan_epic_task as _fn
    return _fn(
        item_id, project, db_path,
        is_dry_run_fn=_parent()._is_dry_run,
        task_update_field_fn=_parent().task_update_field,
    )


def _repair_drift(drift, paired, db_path):
    from yoke_core.engines.resync_apply import _repair_drift as _fn
    return _fn(
        drift, paired, db_path,
        call_domain_sync_fn=_parent()._call_domain_sync,
        is_dry_run_fn=_parent()._is_dry_run,
        query_item_status_fn=_parent()._query_item_status,
    )


def _emit_gh_unavailable_doctor():
    """Retired hook: prior callers emitted WARN HCs when the GitHub App auth was absent.
    bearer-token transports surface the missing-auth condition through their
    own typed errors, so callers SKIP via the canonical reason string.
    """
    from yoke_core.engines.resync_apply import _emit_gh_unavailable_doctor as _fn
    return _fn()
