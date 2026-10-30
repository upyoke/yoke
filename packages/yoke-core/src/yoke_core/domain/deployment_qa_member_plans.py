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


_NO_TARGET: tuple[int | None, int, str] = (None, 0, "")


def _run_targets(conn: Any, run_ids: Iterable[str]) -> dict[str, tuple]:
    """Each run's environment id, project id and environment name."""
    rows = query_rows(
        conn,
        "SELECT r.id,r.target_environment_id,r.project_id,e.name FROM deployment_runs r "
        "LEFT JOIN environments e ON e.id=r.target_environment_id WHERE r.id=ANY(%s)",
        (sorted({str(run) for run in run_ids}),),
    )
    return {
        str(row["id"]): (
            int(row["target_environment_id"])
            if row["target_environment_id"] is not None
            else None,
            int(row["project_id"] or 0),
            str(row["name"] or ""),
        )
        for row in rows
    }


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
    items = sorted({int(item) for item in item_ids})
    if not items:
        return {}
    target = _run_targets(conn, [run_id]).get(str(run_id), _NO_TARGET)
    return _owed(conn, items, target, _plan_rows(conn, items), {})


def _plan_rows(conn: Any, items: list[int]) -> list[tuple[dict, bool]]:
    rows = [(row, True) for row in _attached_rows(conn, items)]
    return rows + [(row, False) for row in _default_rows(conn, items)]


def _owed(
    conn: Any, items: list[int], run_target: tuple, rows: list, memo: dict
) -> dict[int, set[int]]:
    """Filter plan rows to these items and the run's target.

    ``memo`` keeps one answer per plan and target across the runs of one read.
    """
    from yoke_core.domain.deployment_qa_snapshot_selection import plan_matches_target

    owed: dict[int, set[int]] = {item: set() for item in items}
    environment_id, project_id, name = run_target
    target = {"project": {"id": project_id}, "environment": {"name": name}}
    for row, attached in rows:
        if int(row["item_id"]) not in owed:
            continue
        plan_id = int(row["plan_id"])
        key = (plan_id, run_target)
        if key not in memo:
            memo[key] = plan_matches_target(conn, dict(row), target, environment_id)
            if not memo[key] and int(row["project_id"]) != project_id:
                env = conn.execute("SELECT name FROM environments WHERE id=%s",
                                   (row["target_environment_id"],)).fetchone()
                memo[key] = env is not None and str(env[0]) == name
        if not memo[key]:
            if not attached:
                continue
            if (plan_id, name) not in memo:
                memo[(plan_id, name)] = _cases_target(conn, plan_id, name)
            if not memo[(plan_id, name)]:
                continue
        owed[int(row["item_id"])].add(plan_id)
    return owed


def _plan_facts(conn, items, target, rows, memo):
    attached = {item: set() for item in items}
    for row, _ in rows:
        if int(row["item_id"]) in attached:
            attached[int(row["item_id"])].add(int(row["plan_id"]))
    return {"owed": _owed(conn, items, target, rows, memo), "attached": attached}


def _runs_plan_facts(conn: Any, runs: tuple[str, ...]) -> dict:
    """Every presented run's members' owed plans, one set read per fact."""
    members: dict[str, list[int]] = {str(run): [] for run in runs}
    for row in query_rows(
        conn,
        "SELECT run_id,item_id FROM deployment_run_items WHERE run_id=ANY(%s)",
        (sorted(members),),
    ):
        members[str(row["run_id"])].append(int(row["item_id"]))
    items = sorted({item for found in members.values() for item in found})
    rows = _plan_rows(conn, items) if items else []
    targets = _run_targets(conn, members) if items else {}
    memo: dict = {}
    return {
        run: _plan_facts(conn, found, targets.get(run, _NO_TARGET), rows, memo)
        for run, found in members.items()
    }


def _run_plan_facts(conn: Any, run_id: str) -> dict:
    """Every current member's owed plans, read once per presentation.

    Inside a presentation of several runs, every presented run is read at once.
    """
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    runs = presented_run_ids(conn, str(run_id))
    if runs:
        return presentation_read(
            conn, ("runs_plan_facts", runs), lambda: _runs_plan_facts(conn, runs)
        )[str(run_id)]

    def read():
        rows = query_rows(
            conn, "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (str(run_id),)
        )
        items = [int(row["item_id"]) for row in rows]
        return _plan_facts(conn, items, _run_targets(conn, [run_id]).get(str(run_id), _NO_TARGET),
                           _plan_rows(conn, items) if items else [], {})

    return presentation_read(conn, ("run_plan_facts", str(run_id)), read)


def run_owed_plans(conn: Any, run_id: str) -> dict[int, set[int]]:
    """Each member's owed plans, sharing the same read as all-environment facts."""
    return _run_plan_facts(conn, run_id)["owed"]


def member_plan_disposition(conn: Any, item_id: int, run_id: str) -> tuple[set[int], bool]:
    """Plans owed here and whether any live attached/default plan exists anywhere."""
    facts = _run_plan_facts(conn, run_id)
    if int(item_id) not in facts["owed"]:
        facts = _plan_facts(
            conn, [int(item_id)], _run_targets(conn, [run_id]).get(str(run_id), _NO_TARGET),
            _plan_rows(conn, [int(item_id)]), {},
        )
    return facts["owed"][int(item_id)], bool(facts["attached"][int(item_id)])


def member_plan_ids(conn: Any, item_id: int, run_id: str) -> set[int]:
    owed = run_owed_plans(conn, run_id)
    if int(item_id) in owed:
        return owed[int(item_id)]
    return members_plan_ids(conn, [item_id], run_id)[int(item_id)]


__all__ = ["default_plan_ids", "member_plan_ids", "members_plan_ids", "run_owed_plans"]
