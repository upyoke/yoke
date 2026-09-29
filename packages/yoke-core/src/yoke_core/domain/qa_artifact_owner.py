"""Which project and storage subject own one QA requirement's evidence."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def requirement_storage_owner(conn: Any, requirement_id: int) -> dict[str, Any]:
    """Resolve the project and storage subject owning one QA requirement."""

    from yoke_core.domain.db_helpers import query_one

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = query_one(
        conn,
        "SELECT r.item_id, r.epic_id, r.task_num, r.deployment_run_id, "
        "r.target_env, COALESCE(m.project_id,i.project_id) "
        "AS project_id, p.slug AS project "
        "FROM qa_requirements r "
        "LEFT JOIN items i ON i.id=r.item_id "
        "LEFT JOIN items m ON m.id=r.deployment_member_item_id "
        "LEFT JOIN projects p ON p.id=COALESCE(m.project_id,i.project_id) "
        f"WHERE r.id = {marker}",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"requirement {requirement_id} not found")
    owner = dict(row)
    if owner["project"] is None and owner["deployment_run_id"] is not None:
        deployment_owner = query_one(
            conn,
            "SELECT d.project_id, p.slug AS project "
            "FROM deployment_runs d "
            "LEFT JOIN projects p ON p.id = d.project_id "
            f"WHERE d.id = {marker}",
            (str(owner["deployment_run_id"]),),
        )
        if deployment_owner is not None:
            owner.update(dict(deployment_owner))
    if owner["project"] is None:
        raise ValueError(
            f"requirement {requirement_id} resolves to no project through its "
            f"owner (item_id={owner['item_id']!r}, "
            f"epic_id={owner['epic_id']!r}, "
            f"deployment_run_id={owner['deployment_run_id']!r}); durable "
            "evidence requires an item-owned or deployment-run-owned requirement"
        )
    return owner


__all__ = ["requirement_storage_owner"]
