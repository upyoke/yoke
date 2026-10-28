"""The post-deploy plans a set of a run's items owes, in one read.

An item owes each live post-deploy plan it attaches and, when its workflow
uses project testing defaults, each post-deploy project default. A plan bound
to another environment than the run's is not owed unless it reaches the run's
environment through the authorized hosted bridge
(:func:`deployment_qa_snapshot_selection.plan_matches_target`), or is attached
and has a case that targets the run's environment by name. Reads are per set
and per distinct plan or workflow version, never per item, so a run's cost does
not grow with its members.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows


def _run_target(conn: Any, run_id: str) -> tuple[int | None, int, str]:
    """The run's environment id, project id and environment name."""
    row = query_rows(
        conn,
        "SELECT r.target_environment_id,r.project_id,e.name FROM deployment_runs r "
        "LEFT JOIN environments e ON e.id=r.target_environment_id WHERE r.id=%s",
        (str(run_id),),
    )
    if not row:
        return None, 0, ""
    environment_id = row[0]["target_environment_id"]
    return (
        int(environment_id) if environment_id is not None else None,
        int(row[0]["project_id"] or 0),
        str(row[0]["name"] or ""),
    )


def _cases_target(conn: Any, plan_id: int, name: str) -> bool:
    from yoke_core.domain.qa_plan_case_definition import plan_cases
    from yoke_core.domain.qa_plan_case_targets import case_target_envs

    return bool(name) and any(
        name in case_target_envs(case) for case in plan_cases(conn, int(plan_id))
    )


def _attached_rows(conn: Any, items: list[int]) -> list[dict]:
    from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql

    return query_rows(
        conn,
        "SELECT a.item_id,a.plan_id,p.project_id,p.target_environment_id "
        "FROM qa_plan_item_attachments a "
        "JOIN qa_plans p ON p.id=a.plan_id WHERE a.item_id=ANY(%s) "
        "AND a.qa_phase='post_deploy' AND p.retired_at IS NULL "
        f"AND {live_item_attachment_sql(conn, 'a')}",
        (items,),
    )


def _default_rows(conn: Any, items: list[int]) -> list[dict]:
    """Post-deploy project defaults of items whose workflow uses them."""
    from yoke_core.domain.qa_plan_attachments import (
        workflow_uses_project_testing_defaults,
    )

    rows = query_rows(
        conn,
        "SELECT i.id AS item_id,i.workflow_version_id,d.plan_id,p.project_id,"
        "p.target_environment_id "
        "FROM items i JOIN qa_plan_project_defaults d ON d.project_id=i.project_id "
        "AND d.workflow_id=i.workflow_id JOIN qa_plans p ON p.id=d.plan_id "
        "WHERE i.id=ANY(%s) AND d.qa_phase='post_deploy' AND p.retired_at IS NULL",
        (items,),
    )
    uses: dict[Any, bool] = {}
    for row in rows:
        version = row["workflow_version_id"]
        if version not in uses:
            uses[version] = workflow_uses_project_testing_defaults(
                conn, int(row["item_id"])
            )
    return [row for row in rows if uses[row["workflow_version_id"]]]


def default_plan_ids(conn: Any, item_id: int) -> set[int]:
    """The item's post-deploy project defaults at any environment."""
    return {int(row["plan_id"]) for row in _default_rows(conn, [int(item_id)])}


def members_plan_ids(
    conn: Any, item_ids: Iterable[int], run_id: str
) -> dict[int, set[int]]:
    """Each item's owed post-deploy plans at the run's environment."""
    from yoke_core.domain.deployment_qa_snapshot_selection import plan_matches_target

    items = sorted({int(item) for item in item_ids})
    owed: dict[int, set[int]] = {item: set() for item in items}
    if not items:
        return owed
    environment_id, project_id, name = _run_target(conn, run_id)
    target = {"project": {"id": project_id}, "environment": {"name": name}}
    rows = [(row, True) for row in _attached_rows(conn, items)]
    rows += [(row, False) for row in _default_rows(conn, items)]
    matches: dict[int, bool] = {}
    targeted: dict[int, bool] = {}
    for row, attached in rows:
        plan_id = int(row["plan_id"])
        if plan_id not in matches:
            matches[plan_id] = plan_matches_target(conn, dict(row), target, environment_id)
        if not matches[plan_id]:
            if not attached:
                continue
            if plan_id not in targeted:
                targeted[plan_id] = _cases_target(conn, plan_id, name)
            if not targeted[plan_id]:
                continue
        owed[int(row["item_id"])].add(plan_id)
    return owed


def member_plan_ids(conn: Any, item_id: int, run_id: str) -> set[int]:
    return members_plan_ids(conn, [item_id], run_id)[int(item_id)]


__all__ = ["default_plan_ids", "member_plan_ids", "members_plan_ids"]
