"""Which project commits one workflow dispatch ships, for fleet rehearsal.

A dispatch ships its own project's release commit, and also every project a
stage binds through ``input_bindings``, at the commit the run recorded for that
binding. The dispatched workflow converges each shipped project's databases
with that project's code, so each one owes its own fleet rehearsal. The run's
bound-source record is the only authority for the bound commits: nothing here
guesses a repository from a project name or reads a branch tip.

A bound project's databases serve the same target environment the dispatch
receives, so its coverage is read and recorded under the environment of the
same name on that project. A project without that environment is refused by
the coverage read, never silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from yoke_core.domain import deploy_pipeline_fleet_release_source as release_source


@dataclass(frozen=True)
class ReleaseSource:
    """One project commit the dispatch ships, in a repository holding it."""

    project: str
    repository: str
    release_sha: str


def bound_commits(
    input_bindings: Optional[Mapping[str, Any]],
    bound_inputs: Mapping[str, str],
) -> Tuple[Dict[str, str], str]:
    """Project to the one commit this dispatch's bindings ship, or a refusal."""
    commits: Dict[str, str] = {}
    for key in sorted(input_bindings or {}):
        binding = (input_bindings or {})[key]
        project = str((binding or {}).get("project") or "").strip()
        if not project:
            return {}, (
                f"release fleet rehearsal refused: input binding {key!r} names "
                "no project; declare its project and branch on the flow stage "
                "(`yoke deployment flows update-stages`)"
            )
        sha = str(bound_inputs.get(key) or "").strip()
        if not sha:
            return {}, (
                f"release fleet rehearsal refused: bound input {key!r} of project "
                f"{project!r} has no recorded source commit, so the commit this "
                "dispatch ships is unknown; re-drive the run with `yoke watch deploy -- RUN` so preparation "
                "records it, or compose a new run"
            )
        if commits.setdefault(project, sha) != sha:
            return {}, _inconsistent(project, commits[project], sha)
    return commits, ""


def shipped_projects(project: str, bound: Mapping[str, str]) -> List[str]:
    """The run's own project first, then each bound project once."""
    return [project, *sorted(name for name in bound if name != project)]


def resolve_source(
    source_project: str,
    *,
    project: str,
    repository: str,
    release_lineage: str,
    bound: Mapping[str, str],
) -> Tuple[Optional[ReleaseSource], str]:
    """The repository and exact commit that *source_project* ships."""
    if source_project == project:
        release_sha, error = _release_sha(release_lineage, repository)
        if error:
            return None, error
        bound_sha = bound.get(project, release_sha)
        if bound_sha != release_sha:
            return None, _inconsistent(project, release_sha, bound_sha)
        return ReleaseSource(project, repository, release_sha), ""
    release_sha = bound[source_project]
    checkout = _bound_checkout(source_project)
    if checkout is None:
        return None, (
            f"release fleet rehearsal refused: bound project {source_project!r} "
            "has no checkout registered on this machine, so its commit "
            f"{release_sha} cannot be rehearsed. Register one "
            "(`yoke project register <checkout> --project-id N`), then re-drive "
            "the run"
        )
    error = release_source.ensure_commit(str(checkout), release_sha)
    if error:
        return None, f"release fleet rehearsal refused: {error}"
    return ReleaseSource(source_project, str(checkout), release_sha), ""


def _inconsistent(project: str, first: str, second: str) -> str:
    return (
        f"release fleet rehearsal refused: one dispatch would ship two commits "
        f"of project {project!r} ({first} and {second}); a run carries one "
        "source commit per project, so correct the flow's input_bindings"
    )


def _release_sha(lineage: str, repository: str) -> Tuple[str, str]:
    from yoke_core.domain.deploy_pipeline_github_workflow import (
        _resolve_release_lineage_sha,
    )

    return _resolve_release_lineage_sha(lineage, repository, "")


def _bound_checkout(project: str) -> Optional[Path]:
    from yoke_core.domain.project_checkout_locations import checkout_for_project_slug

    return checkout_for_project_slug(project)


__all__ = [
    "ReleaseSource",
    "bound_commits",
    "resolve_source",
    "shipped_projects",
]
