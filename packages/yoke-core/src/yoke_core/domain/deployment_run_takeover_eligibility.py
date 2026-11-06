"""Select the newest eligible predecessor on a release target."""

from collections.abc import Mapping
from typing import Any, Optional
from yoke_core.domain.db_helpers import query_one
_GATE_RUNNERS = frozenset({"qa", "human-approval"})

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




def eligible_predecessor(conn: Any, new_run: Mapping[str, Any]) -> Optional[dict]:
    """Take over only the newest earlier run on this flow and target, if eligible."""
    from yoke_core.domain.deploy_target_occupancy import open_qa_lines
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    row = query_one(
        conn,
        "SELECT id,status,current_stage,settling_at,release_lineage,supersedes_run_id "
        "FROM deployment_runs "
        "WHERE project_id=%s AND flow=%s AND target_environment_id=%s "
        "AND superseded_by_run_id IS NULL AND status<>'cancelled' "
        "AND id<>%s ORDER BY created_at DESC,id DESC LIMIT 1",
        (
            new_run["project_id"],
            new_run["flow"],
            new_run["target_environment_id"],
            new_run["id"],
        ),
    )
    if row is not None:
        stages = pinned_stages(conn, str(row["id"]))
        eligible = row["status"] in {"created", "failed"} or (
            row["status"] == "executing" and _waits_only_on_qa(row, stages)
        )
        if eligible and (row["status"] in {"created", "failed"}
                         or open_qa_lines(conn, str(row["id"]), first_wait=True)):
            return {**dict(row), "stages": stages}
    return None

