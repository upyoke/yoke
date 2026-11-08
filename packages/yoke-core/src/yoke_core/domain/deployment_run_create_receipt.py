"""Name a creation's predecessor, live target occupant and release instructions."""

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.deployment_run_target_takeover import takeover_available
from yoke_core.domain.deploy_target_occupancy import run_target, occupancies


def continuation_facts(run_id):
    conn = connect(None)
    try:
        row = query_one(conn, "SELECT supersedes_run_id FROM deployment_runs WHERE id=%s",
                        (run_id,)) if takeover_available(conn) else None
        target = run_target(conn, run_id)
        held = occupancies(conn, target.origins, excluding_run=run_id, first_wait=True) if target else []
        return {"supersedes_run_id": str(row[0]) if row and row[0] else None,
                "waiting_for_run_id": held[0].run_id if held else None}
    finally:
        conn.close()


def release_instructions(project):
    """The project's When creating release execution instructions, in full."""
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.workflow_execution_instructions import resolve_execution_instructions

    conn = connect(None)
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError:
            # A run's project need not be a registered row; only
            # all-project instructions can reach it then.
            project_id = None
        return resolve_execution_instructions(
            conn, workflow_id=None, project_id=project_id,
            delivery_point="when_creating_release")
    finally:
        conn.close()
