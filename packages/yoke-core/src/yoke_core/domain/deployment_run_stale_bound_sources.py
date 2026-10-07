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

#: The control-plane read a deploy driver asks before a bound stage dispatches.
BOUND_SOURCES_CURRENT_FUNCTION_ID = "deployment_runs.execution.bound_sources_current"

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


def _release_output_on_frozen(
    conn: Any, *, project_id: int, frozen: str, current: str
) -> tuple[bool, str]:
    """Whether ``current`` is a release's own output written on ``frozen``.

    A release pair's promotion may push a version pin onto the bound branch,
    directly on the commit the pair proved. That moves the branch without
    staling the proof, so a head some run recorded as its release output whose
    first parent is the frozen commit still counts as current. Any other move
    is stale. Returns ``(on_frozen, unverified_reason)``: the reason is set only
    when the head is such a recorded output but its parent cannot be read.
    """
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
        open_carried_work_source,
    )
    from yoke_core.domain.deployment_run_release_output import release_output_runs

    producer = release_output_runs(conn, project_id).get(current.lower())
    if producer is None:
        return False, ""
    try:
        source = open_carried_work_source(conn, project_id)
        parent = str(source.resolve_commit(f"{current}^") or "").strip()
    except CarriedWorkSourceUnavailable as exc:
        return False, (
            f"head {current} is release output of {producer['run_id']}, but its "
            f"parent cannot be read ({exc.reason}: {exc.recovery})"
        )
    if not parent:
        return False, (
            f"head {current} is release output of {producer['run_id']}, but its "
            "parent commit did not resolve; make the project's source readable "
            "here, then re-drive the run"
        )
    return parent.lower() == frozen.lower(), ""


def _compare_to_branch_heads(
    conn: Any,
    run_id: str,
    entries: list[dict[str, Any]],
    branches: dict[str, str],
) -> tuple[list[dict[str, str]], str]:
    """Compare each recorded commit with its branch's current head."""
    stale: list[dict[str, str]] = []
    unverified: list[str] = []
    for entry in entries:
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
        on_frozen, unreadable = _release_output_on_frozen(
            conn, project_id=int(entry["project_id"]), frozen=frozen, current=current
        )
        if unreadable:
            unverified.append(f"bound source {project} {frozen}: {unreadable}")
            continue
        if on_frozen:
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


def _recorded_sources(
    conn: Any, run_id: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The run's recorded bound commits and the branch each was resolved from."""
    if not bound_sources_recorded(conn):
        return [], {}
    row = conn.execute(
        f"SELECT COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD}, "
        "df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return [], {}
    recorded = parse_bound_sources(_cell(row, BOUND_SOURCES_FIELD, 0))
    entries = [dict(entry) for entry in recorded.get("projects") or []]
    if not entries:
        return [], {}
    return entries, _branches_by_project(str(_cell(row, "stages", 1) or ""))


def check_bound_sources_current(
    conn: Any, run_id: str
) -> tuple[list[dict[str, str]], str]:
    """Every recorded bound source whose branch has moved, before a dispatch.

    Returns ``(stale, unverified)`` over all of the run's bound sources. A
    stage that consumes them asks this immediately before dispatching, so a
    run that can no longer pass fails at once instead of after the downstream
    workflow spends its whole run discovering the same thing. Nothing is
    rebound: the recorded commits stay frozen, and the remedy is a new run.
    """
    entries, branches = _recorded_sources(conn, run_id)
    return _compare_to_branch_heads(conn, run_id, entries, branches)


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
    if not failure_text.strip():
        return [], ""
    entries, branches = _recorded_sources(conn, run_id)
    named = [
        entry
        for entry in entries
        if _names_commit(failure_text, str(entry.get("commit_sha") or ""))
    ]
    return _compare_to_branch_heads(conn, run_id, named, branches)


__all__ = [
    "BOUND_SOURCES_CURRENT_FUNCTION_ID",
    "check_bound_sources_current",
    "diagnose_stale_bound_sources",
    "stale_bound_source_reason",
]
