"""Compare bound branches and teach recovery according to durable consumption.

Consumed inputs remain fixed. An unused stale input can be refreshed by the
runner before dispatch; a consumed stale source requires a new release run.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    _resolve_branch_head,
    declared_bindings,
    parse_bound_sources,
)

#: The registered read-only projection of bound-source freshness.
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
    """Compare recorded sources without changing them; name consumption recovery."""
    entries, branches = _recorded_sources(conn, run_id)
    return _recovery_for_consumption(
        conn,
        run_id,
        entries,
        *_compare_to_branch_heads(conn, run_id, entries, branches),
    )


def _recovery_for_consumption(conn, run_id, entries, stale, unverified):
    from yoke_core.domain.deployment_run_bound_source_consumption import (
        source_consumed_by,
    )

    by_project = {entry["project"]: entry for entry in entries}
    for change in stale:
        try:
            consumed = source_consumed_by(conn, run_id, by_project[change["project"]])
        except (LookupError, ValueError) as exc:
            unverified = "; ".join(filter(None, [unverified, str(exc)]))
            continue
        if not consumed:
            change["reason"] = (
                f"bound source {change['project']} {change['frozen_sha']} is stale "
                f"(current {change['current_sha']}) and unused; re-drive {run_id}: "
                "a driver carrying bound source preparation re-binds it before first consumption. "
                "If this run pins an older driver, create a new run on the updated candidate"
            )
    return stale, unverified


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
    return _recovery_for_consumption(
        conn, run_id, named, *_compare_to_branch_heads(conn, run_id, named, branches)
    )


__all__ = [
    "BOUND_SOURCES_CURRENT_FUNCTION_ID",
    "check_bound_sources_current",
    "diagnose_stale_bound_sources",
    "stale_bound_source_reason",
]
