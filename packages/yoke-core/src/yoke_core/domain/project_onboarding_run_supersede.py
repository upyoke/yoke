"""Close onboarding checklist runs a project's deployments have overtaken.

An onboarding checklist run row appears the moment the skill opens it and
stays open until every row closes. A project that has since deployed is
past onboarding whatever its checklist says: the yoke project itself carried
a run blocked at its setup step months after it shipped hundreds of
releases, and the Overview read it as "next up". The run row is the
durable record of what onboarding did, so the reconciliation writes the
fact onto it instead of filtering it out of a read: the run's status becomes
``superseded`` and its metadata names the deployment run that overtook it.
The checklist rows keep their own statuses — they are still true.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import json_helper
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _table_exists

RUN_STATUS_SUPERSEDED = "superseded"

#: Metadata key on ``project_onboarding_runs.metadata_json`` naming the
#: deployment run that closed the checklist.
SUPERSEDED_BY_KEY = "superseded_by_deployment"

RUNS_TABLE = "project_onboarding_runs"
DEPLOYMENT_RUNS_TABLE = "deployment_runs"


def _overtaking_deployment(
    conn: Any, project_id: int, run_updated_at: str,
) -> Optional[Dict[str, Any]]:
    """The deployment run that puts *project_id* past onboarding, or None.

    A succeeded deployment settles it outright. Failing that, any deployment
    run newer than the checklist's last write does: the project moved on to
    delivery after the checklist stalled.
    """
    succeeded = conn.execute(
        f"SELECT id, status, COALESCE(completed_at, created_at) FROM {DEPLOYMENT_RUNS_TABLE} "
        "WHERE project_id = %s AND status = 'succeeded' "
        "ORDER BY COALESCE(completed_at, created_at) DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if succeeded is None:
        succeeded = conn.execute(
            f"SELECT id, status, COALESCE(completed_at, created_at) FROM {DEPLOYMENT_RUNS_TABLE} "
            "WHERE project_id = %s AND COALESCE(completed_at, created_at) > %s "
            "ORDER BY COALESCE(completed_at, created_at) DESC LIMIT 1",
            (project_id, run_updated_at),
        ).fetchone()
    if succeeded is None:
        return None
    return {
        "deployment_run_id": str(succeeded[0]),
        "status": str(succeeded[1]),
        "at": succeeded[2],
    }


def supersede_overtaken_runs(conn: Any) -> List[Dict[str, Any]]:
    """Mark every open checklist run its project's deployments overtook.

    Idempotent: a run already ``superseded`` is left alone, and a run whose
    project has not deployed is untouched. Returns the reconciled runs.
    """
    if not (_table_exists(conn, RUNS_TABLE) and _table_exists(conn, DEPLOYMENT_RUNS_TABLE)):
        return []
    candidates = conn.execute(
        f"SELECT run_id, project_id, updated_at, metadata_json FROM {RUNS_TABLE} "
        "WHERE project_id IS NOT NULL AND status <> %s",
        (RUN_STATUS_SUPERSEDED,),
    ).fetchall()
    reconciled: List[Dict[str, Any]] = []
    now = iso8601_now()
    for run_id, project_id, updated_at, metadata_json in candidates:
        deployment = _overtaking_deployment(conn, int(project_id), str(updated_at))
        if deployment is None:
            continue
        metadata = dict(json_helper.loads_text(metadata_json or "{}"))
        metadata[SUPERSEDED_BY_KEY] = {**deployment, "reconciled_at": now}
        conn.execute(
            f"UPDATE {RUNS_TABLE} SET status = %s, metadata_json = %s, updated_at = %s "
            "WHERE run_id = %s",
            (RUN_STATUS_SUPERSEDED, json_helper.dumps_compact(metadata), now, run_id),
        )
        reconciled.append({"run_id": str(run_id), "project_id": int(project_id), **deployment})
    if reconciled:
        conn.commit()
    return reconciled


def superseded_by(metadata_json: Optional[str]) -> Optional[Dict[str, Any]]:
    """The overtaking deployment recorded on a run's metadata, if any."""
    try:
        metadata = json_helper.loads_text(metadata_json or "{}")
    except ValueError:
        return None
    value = metadata.get(SUPERSEDED_BY_KEY) if isinstance(metadata, dict) else None
    return dict(value) if isinstance(value, dict) else None


__all__ = [
    "DEPLOYMENT_RUNS_TABLE",
    "RUNS_TABLE",
    "RUN_STATUS_SUPERSEDED",
    "SUPERSEDED_BY_KEY",
    "supersede_overtaken_runs",
    "superseded_by",
]
