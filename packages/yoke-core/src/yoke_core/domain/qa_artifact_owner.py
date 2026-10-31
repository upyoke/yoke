"""Which project and storage subject own one QA requirement's evidence."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_activity_selection import project_of_requirement


def requirement_storage_owner(conn: Any, requirement_id: int) -> dict[str, Any]:
    """Resolve the project and storage subject owning one QA requirement."""

    from yoke_core.domain.db_helpers import query_one

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project = project_of_requirement(member="m", plan="qp", item="i", run="d")
    row = query_one(
        conn,
        "SELECT COALESCE(r.item_id,r.epic_id) AS item_id, r.epic_id, "
        "r.task_num, r.deployment_run_id, r.target_env, "
        "r.standalone_execution_id, r.plan_id, "
        f"{project} AS project_id, p.slug AS project "
        "FROM qa_requirements r "
        "LEFT JOIN items i ON i.id=COALESCE(r.item_id,r.epic_id) "
        "LEFT JOIN items m ON m.id=r.deployment_member_item_id "
        "LEFT JOIN qa_plans qp ON qp.id=r.plan_id "
        "LEFT JOIN deployment_runs d ON d.id=r.deployment_run_id "
        f"LEFT JOIN projects p ON p.id={project} "
        f"WHERE r.id = {marker}",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"requirement {requirement_id} not found")
    owner = dict(row)
    if owner["project"] is None:
        raise ValueError(
            f"requirement {requirement_id} resolves to no project through its "
            f"owner (item_id={owner['item_id']!r}, "
            f"epic_id={owner['epic_id']!r}, "
            f"deployment_run_id={owner['deployment_run_id']!r}); durable "
            "evidence requires a deployment member, plan, item, or deployment-run owner"
        )
    return owner


__all__ = ["requirement_storage_owner"]
