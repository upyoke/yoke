"""Publish commit-cache aggregates into ``project_code_days`` before board fetch."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def build_code_days_payload(repo_root: Path) -> List[Dict[str, Any]]:
    """Warm the local commit cache and return upsert rows for ``board.data.get``."""

    from yoke_contracts.board.widgets_commit_cache import (
        aggregate_cache_for_projects,
        get_commit_data,
    )
    from yoke_contracts.machine_config import runtime as machine_config
    from yoke_contracts.machine_config.schema import mapped_checkouts

    config = machine_config.load_config()
    repo_to_project: Dict[str, int] = {}
    repos: List[str] = []
    for checkout, project_id in mapped_checkouts(config):
        path = Path(str(checkout)).expanduser()
        if not path.is_dir():
            continue
        resolved = str(path.resolve())
        repo_to_project[resolved] = int(project_id)
        repo_to_project[str(path)] = int(project_id)
        repos.append(resolved)
    root = str(repo_root.resolve())
    if root not in repo_to_project:
        project_id = machine_config.project_id(repo_root)
        if project_id is not None:
            repo_to_project[root] = int(project_id)
            repos.append(root)
    if not repos:
        return []
    cache = get_commit_data(repos)
    return aggregate_cache_for_projects(cache, repo_to_project)


def publish_code_days_via_board_payload(
    request_payload: Dict[str, Any],
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    """Attach ``code_days`` aggregates to a ``board.data.get`` payload."""

    rows = build_code_days_payload(repo_root)
    if rows:
        request_payload = dict(request_payload)
        request_payload["code_days"] = rows
    return request_payload


__all__ = [
    "build_code_days_payload",
    "publish_code_days_via_board_payload",
]
