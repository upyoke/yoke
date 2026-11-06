"""Select the newest eligible predecessor on a release target."""

from collections.abc import Mapping
from typing import Any, Optional
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.deployment_run_target_takeover import _waits_only_on_qa

def _waiting_run(conn: Any, new_run: Mapping[str, Any]) -> Optional[dict]:
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
        eligible = not row["settling_at"] and (row["status"] in {"created", "failed"} or (
            row["status"] == "executing" and _waits_only_on_qa(row, stages)
        ))
        if eligible and (row["status"] in {"created", "failed"}
                         or open_qa_lines(conn, str(row["id"]), first_wait=True)):
            return {**dict(row), "stages": stages}
    return None

