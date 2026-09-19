"""One project's carried set: what this run adds over the run before it.

A run ships a commit per project it carries, so the comparison is written
once and asked once per project. The base is whatever the preceding run
recorded for that same project, which is what lets a bound project be
compared against the commit that release actually shipped for it rather than
against a lineage belonging to the carrier.

An answer nobody could compute is not an empty release, so every exit that
could not look says so by name: :func:`empty_carried_work` carries the
reason, the recovery, and the flag readers key on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_DIVERGED,
    CarriedWorkSource,
    CarriedWorkSourceUnavailable,
    open_carried_work_source,
)
from yoke_core.domain.deployment_run_carried_work_sources import (
    resolve_carried_items,
)


CARRIED_WORK_SCHEMA = 2
# An answer nobody could compute is not an empty release. Readers key on the
# status, so it is derived from the one flag that says whether the comparison
# actually ran rather than set by hand at each exit.
STATUS_DERIVED = "derived"
STATUS_EMPTY = "empty"
STATUS_UNKNOWN = "unknown"
SOURCE_NONE = "none"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def empty_carried_work(
    reason: str,
    recovery: str,
    *,
    run_id: str,
    contents_known: bool = False,
    previous_run_id: str = "",
    previous_lineage: str = "",
    release_lineage: str = "",
    warnings: Sequence[Mapping[str, str]] = (),
    error_type: str = "",
    source: str = SOURCE_NONE,
) -> dict[str, Any]:
    # An empty answer and an unanswerable question are different facts, and a
    # reader that conflates them tells an approver a release is empty when the
    # deriver simply could not look. `contents_known` is true only when the
    # comparison actually ran: a run whose lineage matches its predecessor
    # genuinely carries nothing, while a missing checkout carries an unknown.
    derivation: dict[str, Any] = {
        "status": STATUS_EMPTY if contents_known else STATUS_UNKNOWN,
        "contents_known": contents_known,
        "source": source,
        "reason": reason,
        "recovery": recovery,
        "run_id": run_id,
        "previous_run_id": previous_run_id,
        "previous_release_lineage": previous_lineage,
        "release_lineage": release_lineage,
    }
    if error_type:
        derivation["error_type"] = error_type
    return {
        "schema": CARRIED_WORK_SCHEMA,
        "derivation": derivation,
        "items": [],
        "commits": [],
        "warnings": [dict(warning) for warning in warnings],
    }


def derive_project_carried_work(
    conn: Any,
    run_id: str,
    *,
    project_id: int,
    release_lineage: str,
    previous: Any,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Compare one project's recorded commit against the preceding run's.

    ``previous`` is the run row this one follows; the base commit is what
    that run recorded for this same project, so a bound project is compared
    against the bound commit shipped last time rather than against a lineage
    belonging to the carrier.
    """
    release_lineage = str(release_lineage or "").strip()
    if not release_lineage:
        return empty_carried_work(
            "current_release_lineage_missing",
            "Start the run with an immutable commit release_lineage.",
            run_id=run_id,
        )
    if previous is None:
        return empty_carried_work(
            "no_prior_succeeded_run",
            "No action is required; this run establishes the lineage baseline.",
            run_id=run_id,
            release_lineage=release_lineage,
        )
    previous_run_id = str(_cell(previous, "id", 0))
    previous_lineage = recorded_source_sha(
        {
            "project_id": _cell(previous, "project_id", 1),
            "release_lineage": _cell(previous, "release_lineage", 2),
            "bound_sources": _cell(previous, "bound_sources", 3),
        },
        int(project_id),
    )
    if not previous_lineage:
        return empty_carried_work(
            "prior_release_lineage_missing",
            "Repair the previous run's immutable release_lineage before retrying.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            release_lineage=release_lineage,
        )
    try:
        source: CarriedWorkSource = open_carried_work_source(
            conn, project_id, repo_root=repo_root
        )
    except CarriedWorkSourceUnavailable as exc:
        return empty_carried_work(
            exc.reason,
            exc.recovery,
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
        )
    base = source.resolve_commit(previous_lineage)
    head = source.resolve_commit(release_lineage)
    if not base or not head:
        reason = (
            "prior_release_lineage_unreachable"
            if not base
            else "current_release_lineage_unreachable"
        )
        return empty_carried_work(
            reason,
            "Make both recorded lineages readable from the comparison source, "
            "then retry.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
            source=source.origin,
        )
    try:
        commit_range = source.commit_range(base, head)
    except CarriedWorkSourceUnavailable as exc:
        return empty_carried_work(
            exc.reason,
            exc.recovery,
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
            source=source.origin,
        )
    if commit_range.relation == RELATION_DIVERGED:
        return empty_carried_work(
            "release_lineages_diverged",
            "Correct the run lineage or restore its trunk ancestry, then retry.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
            source=source.origin,
        )
    commits = commit_range.commits
    if not commits:
        return empty_carried_work(
            "no_new_commits",
            "No action is required; both runs resolve to the same trunk tree.",
            run_id=run_id,
            contents_known=True,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
            source=source.origin,
        )
    known_items, resolved, warnings = resolve_carried_items(
        conn,
        project_id=project_id,
        source=source,
        base=base,
        head=head,
        commits=commits,
    )
    item_commits: dict[int, list[str]] = {}
    bare_commits: list[str] = []
    for commit in commits:
        item_ids = sorted(resolved.get(commit, set()))
        if not item_ids:
            bare_commits.append(commit)
        for item_id in item_ids:
            item_commits.setdefault(item_id, []).append(commit)
    return {
        "schema": CARRIED_WORK_SCHEMA,
        "derivation": {
            "status": STATUS_DERIVED,
            "contents_known": True,
            "source": source.origin,
            "reason": "partial_item_resolution" if bare_commits else "complete",
            "recovery": (
                "Inspect bare commits and restore missing merge metadata if needed."
                if bare_commits
                else "No action is required."
            ),
            "run_id": run_id,
            "previous_run_id": previous_run_id,
            "previous_release_lineage": previous_lineage,
            "release_lineage": release_lineage,
        },
        "items": [
            {
                "item_id": item_id,
                "ref": known_items[item_id],
                "commit_shas": shas,
            }
            for item_id, shas in item_commits.items()
        ],
        "commits": bare_commits,
        "warnings": warnings,
    }


__all__ = [
    "CARRIED_WORK_SCHEMA",
    "SOURCE_NONE",
    "STATUS_DERIVED",
    "STATUS_EMPTY",
    "STATUS_UNKNOWN",
    "derive_project_carried_work",
    "empty_carried_work",
]
