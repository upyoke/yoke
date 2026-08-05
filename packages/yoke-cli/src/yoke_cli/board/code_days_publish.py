"""Build ``code_days`` aggregates for ``board.data.get`` from the commit cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def code_days_for_checkout(
    repo_root: Path,
    *,
    settings_project_id: Optional[int],
    load_config,
) -> List[Dict[str, Any]]:
    """Warm the commit cache and fold it into per-(project, day) rows."""

    from yoke_contracts.board.widgets_commit_cache import (
        aggregate_cache_for_projects,
        get_commit_data,
    )
    from yoke_contracts.machine_config.schema import mapped_checkouts

    repo_to_project: Dict[str, int] = {}
    repos: List[str] = []
    for checkout, project_id in mapped_checkouts(load_config()):
        path = Path(str(checkout)).expanduser()
        if not path.is_dir():
            continue
        resolved = str(path.resolve())
        repo_to_project[resolved] = int(project_id)
        repos.append(resolved)
    root_resolved = str(repo_root.resolve())
    if root_resolved not in repo_to_project and settings_project_id is not None:
        repo_to_project[root_resolved] = int(settings_project_id)
        repos.append(root_resolved)
    if not repos:
        return []
    return aggregate_cache_for_projects(get_commit_data(repos), repo_to_project)


__all__ = ["code_days_for_checkout"]
