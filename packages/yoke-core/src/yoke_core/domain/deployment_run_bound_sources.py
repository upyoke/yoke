"""Every project's source commit one run pins, not only the project it owns.

``release_lineage`` names the commit of the project the run belongs to. A
flow stage may additionally bind another registered project's branch through
``input_bindings``, and the build it dispatches ships that project's code
alongside its own. Recording only the branch would leave the run unable to
say what it shipped: the branch moves, so every later question — which items
did this release carry, has this merge been delivered, what is the delivery
box looking at — would re-resolve to a different answer than the one that was
built.

So each declared branch resolves exactly once, at start, and the resolved
commit is stored beside the run's own lineage. Enrollment, composition
validation, the dispatch that substitutes the placeholder, run detail and the
delivery summary all read that record. Nothing re-resolves a branch after
start.

A run records at most one source commit per project, because delivery is
judged per project: two branches of one project in a single run would make
"did this release ship that item" unanswerable.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from yoke_core.domain.json_helper import dumps_compact, loads_text


BOUND_SOURCES_FIELD = "bound_sources"
BOUND_SOURCES_SCHEMA = 1


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def declared_bindings(stages: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """Every ``input_bindings`` entry a flow's stages declare, by input name.

    Two stages declaring the same input name against the same project and
    branch are one binding; declaring it against different ones is a flow
    defect, because the run can hold only one value for that input.
    """
    declared: dict[str, dict[str, str]] = {}
    for stage in stages or ():
        bindings = stage.get("input_bindings") if isinstance(stage, Mapping) else None
        for key, binding in (bindings or {}).items():
            if not isinstance(binding, Mapping):
                raise ValueError(
                    f"input binding {key!r} must name a project and a branch"
                )
            entry = {
                "project": str(binding.get("project") or ""),
                "branch": str(binding.get("branch") or ""),
            }
            if not entry["project"] or not entry["branch"]:
                raise ValueError(
                    f"input binding {key!r} is missing project/branch"
                )
            existing = declared.get(key)
            if existing is not None and existing != entry:
                raise ValueError(
                    f"input binding {key!r} is declared twice with different "
                    f"sources ({existing} and {entry}); one run can hold only "
                    "one value for an input"
                )
            declared[key] = entry
    return declared


def parse_bound_sources(value: Any) -> dict[str, Any]:
    """Return one stored record, or the empty record for no bindings."""
    empty: dict[str, Any] = {
        "schema": BOUND_SOURCES_SCHEMA,
        "projects": [],
        "inputs": {},
    }
    if value in (None, ""):
        return empty
    payload = dict(value) if isinstance(value, Mapping) else None
    if payload is None:
        try:
            parsed = loads_text(str(value))
        except (TypeError, ValueError):
            return empty
        payload = dict(parsed) if isinstance(parsed, Mapping) else None
    if payload is None:
        return empty
    payload.setdefault("schema", BOUND_SOURCES_SCHEMA)
    payload.setdefault("projects", [])
    payload.setdefault("inputs", {})
    return payload


def bound_input_values(payload: Mapping[str, Any]) -> dict[str, str]:
    """The resolved commit each declared workflow input carries."""
    inputs = payload.get("inputs") or {}
    return {str(key): str(value or "") for key, value in inputs.items()}


def bound_project_shas(payload: Mapping[str, Any]) -> dict[int, str]:
    """Project id to the commit this run recorded for it."""
    shas: dict[int, str] = {}
    for entry in payload.get("projects") or []:
        if not isinstance(entry, Mapping):
            continue
        project_id = entry.get("project_id")
        sha = str(entry.get("commit_sha") or "").strip()
        if project_id is not None and sha:
            shas[int(project_id)] = sha
    return shas


def _resolve_branch_head(conn: Any, *, project: str, project_id: int, branch: str) -> str:
    """The exact commit ``branch`` names now, from whichever host can say.

    A machine holding the project's checkout asks its remote directly. A
    control plane serving an HTTPS-only project holds no checkout and reads
    the same tip through the binding the project already authorized. Neither
    answering is a refusal naming both repairs, never a silent empty.
    """
    from yoke_core.domain.deploy_pipeline_github_workflow_bindings import (
        resolve_branch_head_sha,
    )
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
    )
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    reasons: list[str] = []
    checkout = checkout_for_project_id(int(project_id))
    if checkout is not None:
        sha, error = resolve_branch_head_sha(str(checkout), branch)
        if sha:
            return sha
        reasons.append(error)
    from yoke_core.domain.deployment_run_carried_work_repository import (
        open_repository_provider_source,
    )

    try:
        sha = open_repository_provider_source(conn, int(project_id)).resolve_commit(
            branch
        )
    except CarriedWorkSourceUnavailable as exc:
        reasons.append(f"{exc.reason}: {exc.recovery}")
    else:
        if sha:
            return sha
        reasons.append(
            f"the repository binding for project {project!r} resolved no "
            f"commit for branch '{branch}'"
        )
    raise ValueError(
        f"could not resolve branch '{branch}' of bound project {project!r}: "
        + "; ".join(reason for reason in reasons if reason)
        + ". Register that project's checkout "
        "(yoke project register <checkout> --project-id N) or authorize its "
        "repository binding, then start the run again"
    )


def copy_bound_sources(conn: Any, source_run_id: str, run_id: str) -> None:
    """Carry one run's recorded source commits onto its retry, unresolved.

    Retrying a candidate means retrying every commit it pinned. Letting the
    retry resolve its own would quietly turn a retry into a different
    release the moment a bound branch had moved.
    """
    from yoke_core.domain.schema_common import _column_exists

    if not _column_exists(conn, "deployment_runs", BOUND_SOURCES_FIELD):
        return
    marker = _p(conn)
    conn.execute(
        f"UPDATE deployment_runs SET {BOUND_SOURCES_FIELD}=("
        f"SELECT {BOUND_SOURCES_FIELD} FROM deployment_runs WHERE id={marker}"
        f") WHERE id={marker}",
        (source_run_id, run_id),
    )


def record_bound_sources(conn: Any, run_id: str) -> dict[str, Any]:
    """Resolve and store this run's bound source commits, once and forever.

    Forward-only in the caller's transaction, exactly like the run's own
    lineage: a second start, a retry, or a later reader gets the commit the
    first resolution chose rather than wherever the branch has moved since.
    """
    from yoke_core.domain.project_identity import resolve_project_id

    marker = _p(conn)
    row = conn.execute(
        f"SELECT COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD},"
        f"df.stages FROM deployment_runs dr "
        f"JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    stored = str(_cell(row, BOUND_SOURCES_FIELD, 0) or "")
    if stored:
        return parse_bound_sources(stored)
    stages = json.loads(str(_cell(row, "stages", 1) or "[]"))
    declared = declared_bindings(stages)
    projects: dict[str, dict[str, Any]] = {}
    inputs: dict[str, str] = {}
    for key in sorted(declared):
        project = declared[key]["project"]
        branch = declared[key]["branch"]
        project_id = resolve_project_id(conn, project)
        existing = projects.get(project)
        if existing is None:
            sha = _resolve_branch_head(
                conn, project=project, project_id=int(project_id), branch=branch
            )
            projects[project] = {
                "project": project,
                "project_id": int(project_id),
                "commit_sha": sha,
            }
        else:
            sha = str(existing["commit_sha"])
        inputs[key] = sha
    payload = {
        "schema": BOUND_SOURCES_SCHEMA,
        "projects": [projects[name] for name in sorted(projects)],
        "inputs": inputs,
    }
    conn.execute(
        f"UPDATE deployment_runs SET {BOUND_SOURCES_FIELD}={marker} WHERE id={marker}",
        (dumps_compact(payload), run_id),
    )
    return payload


__all__ = [
    "BOUND_SOURCES_FIELD",
    "BOUND_SOURCES_SCHEMA",
    "bound_input_values",
    "bound_project_shas",
    "copy_bound_sources",
    "declared_bindings",
    "parse_bound_sources",
    "record_bound_sources",
]
