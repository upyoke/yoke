"""Resolve the project and naming facts one QA review decision needs.

A requirement reaches review from any of three homes -- a plan case, an item or
epic, or a deployment run -- and the decision surface needs the same facts from
all three: which project's roster may answer, and what to call the thing being
reviewed. Without a project there is no authority to address, so an
unattributable requirement refuses rather than producing an unanswerable ask.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def requirement_facts(conn: Any, requirement_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id, item_id, epic_id, deployment_run_id, plan_id, "
        "plan_case_key, method_id, method_name, expected_outcome, qa_kind, "
        "success_policy "
        "FROM qa_requirements "
        f"WHERE id = {p}",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"QA requirement {requirement_id} does not exist")
    value = {key: row[key] for key in row.keys()}
    if value.get("plan_id") is not None:
        project = conn.execute(
            f"SELECT project_id, name FROM qa_plans WHERE id = {p}",
            (int(value["plan_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
            value["plan_name"] = str(project[1])
    if (
        value.get("method_id") is not None
        and value.get("method_name") is None
        and value.get("plan_id") is None
    ):
        method = conn.execute(
            f"SELECT name FROM qa_methods WHERE id = {p}",
            (str(value["method_id"]),),
        ).fetchone()
        if method is not None:
            value["method_name"] = str(method[0])
    item_id = value.get("item_id") or value.get("epic_id")
    if value.get("project_id") is None and item_id is not None:
        project = conn.execute(
            f"SELECT project_id, title FROM items WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
            value["item_title"] = str(project[1])
    if value.get("project_id") is None and value.get("deployment_run_id"):
        project = conn.execute(
            f"SELECT project_id FROM deployment_runs WHERE id = {p}",
            (str(value["deployment_run_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
    if value.get("project_id") is None:
        raise ValueError(f"QA requirement {requirement_id} has no project authority")
    return value



__all__ = ["requirement_facts"]
