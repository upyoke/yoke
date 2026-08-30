"""Derive and persist the source changes carried by a deployment run.

Run membership answers which items the pipeline owns. Carried work answers a
different question: which trunk changes exist between the preceding release
lineage and this run's lineage. The result therefore lives on the run and
never writes ``deployment_run_items`` or item lifecycle state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.deployment_run_carried_work_sources import (
    resolve_carried_items,
)
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


CARRIED_WORK_FIELD = "carried_work"
CARRIED_WORK_SCHEMA = 1


def parse_carried_work(value: Any) -> dict[str, Any] | None:
    """Return one stored carried-work object, or ``None`` for no record."""
    if value in (None, ""):
        return None
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = loads_text(str(value))
    except (TypeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _empty(
    reason: str,
    recovery: str,
    *,
    run_id: str,
    previous_run_id: str = "",
    previous_lineage: str = "",
    release_lineage: str = "",
    warnings: Sequence[Mapping[str, str]] = (),
    error_type: str = "",
) -> dict[str, Any]:
    derivation: dict[str, Any] = {
        "status": "empty",
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


def _previous_run(conn: Any, run_id: str, project_id: int, environment_id: Any):
    return conn.execute(
        "SELECT id,release_lineage,completed_at FROM deployment_runs "
        "WHERE project_id=%s AND status='succeeded' AND id<>%s "
        "AND target_environment_id IS NOT DISTINCT FROM %s "
        "ORDER BY completed_at DESC NULLS LAST,created_at DESC,id DESC LIMIT 1",
        (project_id, run_id, environment_id),
    ).fetchone()


def _resolved_commit(repo_root: str, lineage: str) -> str:
    return git.git_out(
        repo_root,
        "rev-parse",
        "--verify",
        f"{lineage}^{{commit}}",
    )


def derive_carried_work(
    conn: Any,
    run_id: str,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Derive one run's carried set without changing membership or items."""
    row = conn.execute(
        "SELECT project_id,target_environment_id,release_lineage "
        "FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    project_id = int(_cell(row, "project_id", 0))
    environment_id = _cell(row, "target_environment_id", 1)
    release_lineage = str(_cell(row, "release_lineage", 2) or "").strip()
    if not release_lineage:
        return _empty(
            "current_release_lineage_missing",
            "Start the run with an immutable commit release_lineage.",
            run_id=run_id,
        )
    previous = _previous_run(conn, run_id, project_id, environment_id)
    if previous is None:
        return _empty(
            "no_prior_succeeded_run",
            "No action is required; this run establishes the lineage baseline.",
            run_id=run_id,
            release_lineage=release_lineage,
        )
    previous_run_id = str(_cell(previous, "id", 0))
    previous_lineage = str(_cell(previous, "release_lineage", 1) or "").strip()
    if not previous_lineage:
        return _empty(
            "prior_release_lineage_missing",
            "Repair the previous run's immutable release_lineage before retrying.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            release_lineage=release_lineage,
        )
    checkout = Path(repo_root) if repo_root else checkout_for_project_id(project_id)
    if checkout is None:
        return _empty(
            "project_checkout_unavailable",
            "Register this project's checkout on the deployment machine, then retry.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
        )
    base = _resolved_commit(str(checkout), previous_lineage)
    head = _resolved_commit(str(checkout), release_lineage)
    if not base or not head:
        reason = (
            "prior_release_lineage_unreachable"
            if not base
            else "current_release_lineage_unreachable"
        )
        return _empty(
            reason,
            "Fetch both recorded lineages into the registered checkout, then retry.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
        )
    if not git.is_ancestor(str(checkout), base, head):
        return _empty(
            "release_lineages_diverged",
            "Correct the run lineage or restore its trunk ancestry, then retry.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
        )
    commits = tuple(
        line.strip()
        for line in git.git_out(
            str(checkout),
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{base}..{head}",
        ).splitlines()
        if line.strip()
    )
    if not commits:
        return _empty(
            "no_new_commits",
            "No action is required; both runs resolve to the same trunk tree.",
            run_id=run_id,
            previous_run_id=previous_run_id,
            previous_lineage=previous_lineage,
            release_lineage=release_lineage,
        )
    known_items, resolved, warnings = resolve_carried_items(
        conn,
        project_id=project_id,
        repo_root=str(checkout),
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
            "status": "derived",
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


def record_carried_work(conn: Any, run_id: str) -> dict[str, Any]:
    """Write a forward-only carried-work record in the caller's transaction."""
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    existing = parse_carried_work(_cell(row, CARRIED_WORK_FIELD, 0))
    if existing is not None:
        return existing
    conn.execute("SAVEPOINT carried_work_derivation")
    try:
        payload = derive_carried_work(conn, run_id)
    except Exception as exc:  # noqa: BLE001 - completion records named emptiness
        conn.execute("ROLLBACK TO SAVEPOINT carried_work_derivation")
        conn.execute("RELEASE SAVEPOINT carried_work_derivation")
        payload = _empty(
            "derivation_failed",
            "Repair the named checkout or metadata read, clear this field, and retry.",
            run_id=run_id,
            error_type=type(exc).__name__,
        )
    else:
        conn.execute("RELEASE SAVEPOINT carried_work_derivation")
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (dumps_compact(payload), run_id),
    )
    return payload


__all__ = [
    "CARRIED_WORK_FIELD",
    "CARRIED_WORK_SCHEMA",
    "derive_carried_work",
    "parse_carried_work",
    "record_carried_work",
]
