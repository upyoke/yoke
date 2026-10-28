"""The post-deploy plans a set of items owes at one environment, in one read.

An item owes each live post-deploy plan it attaches and, when its workflow
uses project testing defaults, each post-deploy project default. A plan bound
to another environment is not owed, except an attached one with a case that
targets this environment by name. Reads are per set and per distinct plan or workflow
version, never per item, so a run's cost does not grow with its members.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_rows


def _environment_name(conn: Any, environment_id: int | None) -> str:
    if environment_id is None:
        return ""
    row = conn.execute(
        "SELECT name FROM environments WHERE id=%s", (int(environment_id),)
    ).fetchone()
    return str(row[0]) if row else ""


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
        "SELECT a.item_id,a.plan_id,p.target_environment_id FROM qa_plan_item_attachments a "
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
        "SELECT i.id AS item_id,i.workflow_version_id,d.plan_id,p.target_environment_id "
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
    conn: Any, item_ids: Iterable[int], environment_id: int | None
) -> dict[int, set[int]]:
    """Each item's owed post-deploy plans at this environment."""
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        plan_matches_stage_environment,
    )

    items = sorted({int(item) for item in item_ids})
    owed: dict[int, set[int]] = {item: set() for item in items}
    if not items:
        return owed
    rows = [(row, True) for row in _attached_rows(conn, items)]
    rows += [(row, False) for row in _default_rows(conn, items)]
    name, targeted = None, {}
    for row, attached in rows:
        plan_id = int(row["plan_id"])
        if not plan_matches_stage_environment(row["target_environment_id"], environment_id):
            if not attached:
                continue
            if name is None:
                name = _environment_name(conn, environment_id)
            if plan_id not in targeted:
                targeted[plan_id] = _cases_target(conn, plan_id, name)
            if not targeted[plan_id]:
                continue
        owed[int(row["item_id"])].add(plan_id)
    return owed


def member_plan_ids(conn: Any, item_id: int, environment_id: int | None) -> set[int]:
    return members_plan_ids(conn, [item_id], environment_id)[int(item_id)]


__all__ = ["default_plan_ids", "member_plan_ids", "members_plan_ids"]
