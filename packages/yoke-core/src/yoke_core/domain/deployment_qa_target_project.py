"""Project authority for a deployment QA subject's destination."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend


def target_project(conn: Any, subject: Mapping[str, Any]) -> dict[str, Any]:
    project_id = int(subject.get("member_project_id") or subject["project_id"])
    if project_id == int(subject["project_id"]):
        return {
            "id": project_id,
            "slug": str(subject["project_slug"]),
            "name": str(subject["project_name"]),
        }
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT slug,name FROM projects WHERE id={marker} AND org_id={marker}",
        (project_id, int(subject["tenant_id"])),
    ).fetchone()
    if row is None:
        raise ValueError(
            "deployment_member_target_missing: the member project is not registered "
            "in this run's tenant; repair the run membership before starting QA"
        )
    target = subject["stage"].get("target")
    if isinstance(target, Mapping) and target.get("kind") == "run_preview":
        raise ValueError(
            "deployment_member_target_missing: this run's preview receipt locates "
            "only the run project's deployment; select a producer and target that "
            "deploy the member project before starting QA"
        )
    return {"id": project_id, "slug": str(row[0]), "name": str(row[1])}
