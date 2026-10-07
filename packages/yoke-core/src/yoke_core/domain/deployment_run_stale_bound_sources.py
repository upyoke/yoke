"""Name a failed run whose frozen bound source can no longer pass.

A run resolves each bound branch once and keeps that commit for its whole
life, and a retry copies the record unchanged (see
:mod:`deployment_run_bound_sources`). That is what makes a release
reproducible, and it is also why a failure caused by the frozen commit is
permanent for that run: when the bound project's branch has moved and the
failure names the frozen commit — a pair proof refused because the paired
project's trunk moved past it, say — re-driving the run, or retrying it,
re-proves exactly the same stale commit and fails the same way.

Nothing in the raw failure says so. The terminal error speaks in the
downstream project's terms, and the only remedy that works — a new run,
which resolves the branch afresh — has to be inferred. This module compares
each recorded commit against the branch it was resolved from and, for every
one that both moved and is named by the failure, returns a diagnosis whose
``reason`` says plainly that a new run is required.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    _resolve_branch_head,
    bound_sources_recorded,
    declared_bindings,
    parse_bound_sources,
)

#: The shortest commit prefix a failure may use to name the frozen commit.
_MIN_NAMED_PREFIX = 12


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _names_commit(text: str, sha: str) -> bool:
    return bool(sha) and sha[:_MIN_NAMED_PREFIX].lower() in text.lower()


def stale_bound_source_reason(
    run_id: str, *, project: str, frozen_sha: str, current_sha: str
) -> str:
    """The one sentence a reader of the failure needs to act on it."""
    return (
        f"bound source {project} {frozen_sha} is stale (current {current_sha}); "
        f"re-driving {run_id} cannot pass, and neither can a --retry-of run, "
        "which copies the same frozen commit — leave it failed and create a "
        "new run, which binds the current commit"
    )


def _branches_by_project(stages_text: str) -> dict[str, str]:
    declared = declared_bindings(json.loads(stages_text or "[]"))
    return {entry["project"]: entry["branch"] for entry in declared.values()}


def diagnose_stale_bound_sources(
    conn: Any, run_id: str, *, failure_text: str
) -> tuple[list[dict[str, str]], str]:
    """Stale bound sources the failure names, and why the check stopped if it did.

    Returns ``(stale, unverified)``. ``stale`` holds one entry per bound
    project whose recorded commit differs from its branch's current head and
    is named in ``failure_text``. ``unverified`` is empty when every bound
    source the failure names was compared, and otherwise names the source
    whose current head could not be read, with the repair — never a silent
    "not stale".
    """
    if not failure_text.strip() or not bound_sources_recorded(conn):
        return [], ""
    row = conn.execute(
        f"SELECT COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD}, "
        "df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return [], ""
    recorded = parse_bound_sources(_cell(row, BOUND_SOURCES_FIELD, 0))
    named = [
        entry
        for entry in recorded.get("projects") or []
        if _names_commit(failure_text, str(entry.get("commit_sha") or ""))
    ]
    if not named:
        return [], ""
    branches = _branches_by_project(str(_cell(row, "stages", 1) or ""))
    stale: list[dict[str, str]] = []
    unverified: list[str] = []
    for entry in named:
        project = str(entry.get("project") or "")
        frozen = str(entry.get("commit_sha") or "")
        branch = branches.get(project, "")
        if not branch:
            unverified.append(
                f"bound source {project} {frozen}: the run's flow no longer "
                "declares a branch for it, so its current commit is unknown"
            )
            continue
        try:
            current = _resolve_branch_head(
                conn,
                project=project,
                project_id=int(entry["project_id"]),
                branch=branch,
            )
        except ValueError as exc:
            unverified.append(f"bound source {project} {frozen}: {exc}")
            continue
        if current.lower() == frozen.lower():
            continue
        stale.append(
            {
                "project": project,
                "branch": branch,
                "frozen_sha": frozen,
                "current_sha": current,
                "reason": stale_bound_source_reason(
                    run_id, project=project, frozen_sha=frozen, current_sha=current
                ),
            }
        )
    return stale, "; ".join(unverified)


__all__ = ["diagnose_stale_bound_sources", "stale_bound_source_reason"]
