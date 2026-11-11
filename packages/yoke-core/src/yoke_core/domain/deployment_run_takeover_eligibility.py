"""Select the runs a new release supersedes on its flow and target.

The run waiting on item QA is the one occupying the target, so a new release
supersedes it first; superseding only a newer never-started run would leave
the new release blocked behind that occupant. Never-started runs created
after it are absorbed into the same takeover so none of their work is dropped.
"""

from collections.abc import Mapping
from typing import Any
from yoke_core.domain.db_helpers import query_one, query_rows
_GATE_RUNNERS = frozenset({"qa", "human-approval"})
_COLUMNS = "id,status,current_stage,settling_at,release_lineage,supersedes_run_id,created_at"
_ON_TARGET = (
    "FROM deployment_runs WHERE project_id=%s AND flow=%s AND target_environment_id=%s "
    "AND superseded_by_run_id IS NULL AND status<>'cancelled' AND id<>%s "
)


def _is_qa(stage: Mapping[str, Any]) -> bool:
    return stage.get("step_runner") == "qa" and stage.get("scope") in {"item", "run"}


def _waits_only_on_qa(row: Mapping[str, Any], stages: list[dict]) -> bool:
    """Deploy stages are done: the cursor stands on QA, gates follow."""
    names = [str(stage.get("name") or "") for stage in stages]
    current = str(row["current_stage"] or "")
    if row["settling_at"] or current not in names:
        return False
    remaining = stages[names.index(current) :]
    return _is_qa(remaining[0]) and all(
        stage.get("step_runner") in _GATE_RUNNERS
        or (stage == stages[-1] and stage.get("step_runner") == "auto")
        for stage in remaining
    )


def _with_stages(conn: Any, row: Mapping[str, Any]) -> dict:
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    return {**dict(row), "stages": pinned_stages(conn, str(row["id"]))}


def eligible_predecessors(conn: Any, new_run: Mapping[str, Any]) -> list[dict]:
    """The run this creation supersedes, then the never-started runs it absorbs.

    An executing run whose cursor waits only on QA, with an open QA line, is
    superseded ahead of any newer never-started run, and those newer runs
    follow it. Otherwise only the newest run is considered, as a ``created``
    or ``failed`` run. Empty when nothing on the target is eligible.
    """
    from yoke_core.domain.deploy_target_occupancy import open_qa_lines

    params = (
        new_run["project_id"],
        new_run["flow"],
        new_run["target_environment_id"],
        new_run["id"],
    )
    newest_first = "ORDER BY created_at DESC,id DESC"
    started = query_one(
        conn,
        f"SELECT {_COLUMNS} {_ON_TARGET}AND status<>'created' {newest_first} LIMIT 1",
        params,
    )
    unstarted = query_rows(
        conn, f"SELECT {_COLUMNS} {_ON_TARGET}AND status='created' {newest_first}", params
    )
    if started is not None:
        floor = (started["created_at"], str(started["id"]))
        unstarted = [
            row for row in unstarted if (row["created_at"], str(row["id"])) > floor
        ]
        if started["status"] == "executing":
            old = _with_stages(conn, started)
            if _waits_only_on_qa(started, old["stages"]) and open_qa_lines(
                conn, str(started["id"]), first_wait=True
            ):
                return [old, *(_with_stages(conn, row) for row in unstarted)]
    if unstarted:
        return [_with_stages(conn, unstarted[0])]
    if started is not None and started["status"] == "failed":
        return [_with_stages(conn, started)]
    return []
