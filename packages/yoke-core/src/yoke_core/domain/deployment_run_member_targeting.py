"""Admission and custody for releases that answer different item QA targets."""

from __future__ import annotations

import json
from typing import Any


def run_environment_name(conn: Any, run_id: str) -> str:
    """The environment a run delivers to: its own target, else its flow's."""
    row = conn.execute(
        "SELECT e.name FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        "LEFT JOIN environments e ON e.id=COALESCE(dr.target_environment_id,df.target_environment_id) "
        "WHERE dr.id=%s",
        (str(run_id),),
    ).fetchone()
    return str((row[0] if row else "") or "")


def supplemental_qa_run(conn: Any, *, run_id: str, item_id: int) -> bool:
    """A different persistent environment proves QA without final delivery.

    The completion flow remains the delivery authority. This works for an
    own-project run and for a run carrying another project's bound source.
    """
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow

    flow = item_completion_flow(conn, int(item_id))
    return int(item_id) in supplemental_item_ids(
        conn, run_id=run_id, completion_flows={int(item_id): flow}
    )


def supplemental_item_ids(
    conn: Any, *, run_id: str, completion_flows: dict[int, str]
) -> frozenset[int]:
    """Resolve environment differences in one read for the entire member set."""
    from yoke_core.domain import db_backend

    flows = tuple(dict.fromkeys(value for value in completion_flows.values() if value))
    if not flows:
        return frozenset()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT cf.id,re.name,ce.name FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        f"JOIN deployment_flows cf ON cf.id IN ({','.join(marker for _ in flows)}) "
        "LEFT JOIN environments re ON re.id=COALESCE(dr.target_environment_id,df.target_environment_id) "
        "LEFT JOIN environments ce ON ce.id=cf.target_environment_id "
        f"WHERE dr.id={marker}",
        (*flows, str(run_id)),
    ).fetchall()
    supplemental = {
        str(row[0]) for row in rows if row[1] and row[2] and str(row[1]) != str(row[2])
    }
    return frozenset(
        item_id for item_id, flow in completion_flows.items() if flow in supplemental
    )


def run_member_targets(
    conn: Any, *, run_id: str, item_ids
) -> tuple[frozenset[int], dict[int, frozenset[int]]]:
    """One target and intake read for a complete composition candidate set."""
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        outstanding_post_deploy_requirement_sets,
        run_qa_stage_targets,
        stage_target_admits,
    )

    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not ids:
        return frozenset(), {}
    supplemental = supplemental_item_ids(
        conn, run_id=run_id, completion_flows=item_completion_flows(conn, ids)
    )
    environments, dynamic = run_qa_stage_targets(conn, run_id)
    requirements = outstanding_post_deploy_requirement_sets(conn, ids)
    targeted = {
        item_id: frozenset(
            row["id"]
            for row in requirements.get(item_id, ())
            if row["target_env"]
            and stage_target_admits(
                row["target_env"], environments=environments, dynamic=dynamic
            )
        )
        for item_id in ids
    }
    return supplemental, targeted


def targeted_requirement_ids(conn: Any, *, run_id: str, item_id: int) -> frozenset[int]:
    return run_member_targets(conn, run_id=run_id, item_ids=(item_id,))[1][item_id]


def needed_member_ids(conn: Any, *, run_id: str, item_ids) -> frozenset[int]:
    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    supplemental, targeted = run_member_targets(conn, run_id=run_id, item_ids=ids)
    return frozenset(
        item_id for item_id in ids if item_id not in supplemental or targeted[item_id]
    )


def run_needs_member(conn: Any, *, run_id: str, item_id: int) -> bool:
    return item_id in needed_member_ids(conn, run_id=run_id, item_ids=(item_id,))


def _selection_identity(row):
    """Frozen plan case identities stay fixed; pending plans name their live cases."""
    if row["requirement_snapshot"]:
        snapshot = json.loads(str(row["requirement_snapshot"]))
        ids = {int(entry["id"]) for entry in snapshot["requirements"]}
        plans = {
            int(entry["plan"]["id"]): {str(case["case_key"]) for case in entry["cases"]}
            for entry in snapshot.get("plans", ())
        }
    else:
        selection = json.loads(str(row["requirement_selection"] or "{}"))
        ids = {int(value) for value in selection.get("requirement_ids", ())}
        plans = {int(value): None for value in selection.get("plan_ids", ())}
    return ids, plans


def _selected_sets(conn, rows):
    """Read recorded selection identities together, without validation or row locks."""
    identities = {
        (str(row["run_id"]), int(row["item_id"])): _selection_identity(row)
        for row in rows
    }
    pairs = {
        (key[1], plan_id) for key, (_, plans) in identities.items() for plan_id in plans
    }
    plan_requirements = {}
    if pairs:
        items, plans = (
            tuple({pair[0] for pair in pairs}),
            tuple({pair[1] for pair in pairs}),
        )
        requirements = conn.execute(
            f"SELECT item_id,plan_id,id,plan_case_key FROM qa_requirements WHERE item_id IN ({','.join('%s' for _ in items)}) "
            f"AND plan_id IN ({','.join('%s' for _ in plans)}) AND deployment_run_id IS NULL",
            (*items, *plans),
        ).fetchall()
        for item_id, plan_id, requirement_id, case_key in requirements:
            plan_requirements.setdefault((int(item_id), int(plan_id)), []).append(
                (int(requirement_id), str(case_key))
            )
    result = {}
    for key, (ids, plans) in identities.items():
        for plan_id, case_keys in plans.items():
            ids.update(
                requirement_id
                for requirement_id, case_key in plan_requirements.get(
                    (key[1], plan_id), ()
                )
                if case_keys is None or case_key in case_keys
            )
        result[key] = frozenset(ids)
    return result


def covering_holder_pairs(
    conn: Any, *, run_id: str, item_ids, holders
) -> frozenset[tuple[str, int]]:
    """Which holders already deliver what this run would deliver for each item.

    Holding is per target environment. A holder on the item's final target
    keeps final-target custody. For a supplemental run, only a holder on the
    same environment can answer its targeted obligations, so a production run
    never holds an item away from the stage run that owes it stage QA.
    """
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows

    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not holders:
        return frozenset()
    supplemental, wanted = run_member_targets(conn, run_id=run_id, item_ids=ids)
    flows = item_completion_flows(conn, ids)
    holder_ids = tuple(dict.fromkeys(str(row["run_id"]) for row in holders))
    rows = conn.execute(
        "SELECT dri.run_id,dri.item_id,dri.requirement_snapshot,dri.requirement_selection,"
        "re.name AS run_environment "
        "FROM deployment_run_items dri JOIN deployment_runs dr ON dr.id=dri.run_id "
        "JOIN deployment_flows df ON df.id=dr.flow "
        "LEFT JOIN environments re ON re.id=COALESCE(dr.target_environment_id,df.target_environment_id) "
        f"WHERE dri.run_id IN ({','.join('%s' for _ in holder_ids)}) "
        f"AND dri.item_id IN ({','.join('%s' for _ in ids)})",
        (*holder_ids, *ids),
    ).fetchall()
    # Default completion flows may not yet be pinned on an old member.
    flow_envs = (
        conn.execute(
            f"SELECT df.id,e.name FROM deployment_flows df LEFT JOIN environments e ON e.id=df.target_environment_id WHERE df.id IN ({','.join('%s' for _ in flows.values())})",
            tuple(flows.values()),
        ).fetchall()
        if flows
        else ()
    )
    environments = {str(row[0]): str(row[1] or "") for row in flow_envs}
    run_environment = run_environment_name(conn, run_id)
    selected = _selected_sets(conn, rows)
    covered = set()
    for row in rows:
        key = (str(row["run_id"]), int(row["item_id"]))
        item_id = key[1]
        final_environment = environments.get(flows.get(item_id, ""), "")
        holder_supplemental = bool(
            row["run_environment"]
            and final_environment
            and row["run_environment"] != final_environment
        )
        if item_id not in supplemental:
            keep = not holder_supplemental
        elif str(row["run_environment"] or "") != run_environment:
            keep = False
        elif not row["requirement_snapshot"] and not row["requirement_selection"]:
            keep = True
        else:
            keep = wanted[item_id] <= selected[key]
        if keep:
            covered.add(key)
    return frozenset(covered)


def holder_covers_run(conn: Any, *, holder_id: str, run_id: str, item_id: int) -> bool:
    return (holder_id, item_id) in covering_holder_pairs(
        conn, run_id=run_id, item_ids=(item_id,), holders=({"run_id": holder_id},)
    )


def member_selected_requirement_ids(
    conn: Any, *, run_id: str, item_id: int
) -> frozenset[int]:
    rows = conn.execute(
        "SELECT run_id,item_id,requirement_snapshot,requirement_selection FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, item_id),
    ).fetchall()
    return _selected_sets(conn, rows).get((run_id, item_id), frozenset())


def companion_requirement_sets(
    conn: Any, *, run_id: str, item_ids
) -> dict[int, frozenset[int]]:
    """Read sibling selection and candidate identities together, independent of row count."""
    from yoke_core.domain.deployment_run_project_sources import (
        run_source_facts,
        recorded_source_sha,
    )

    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not ids:
        return {}
    current = run_source_facts(conn, run_id)
    rows = conn.execute(
        "SELECT dri.run_id,dri.item_id,dri.requirement_snapshot,dri.requirement_selection,"
        "dr.project_id,dr.release_lineage,dr.bound_sources,i.project_id AS item_project_id "
        "FROM deployment_runs dr JOIN deployment_run_items dri ON dri.run_id=dr.id JOIN items i ON i.id=dri.item_id "
        f"WHERE dri.item_id IN ({','.join('%s' for _ in ids)}) AND dr.id <> %s "
        "AND dr.status IN ('created','executing','succeeded')",
        (*ids, run_id),
    ).fetchall()
    selected = _selected_sets(conn, rows)
    grouped = {}
    for row in rows:
        project_id = int(row["item_project_id"])
        lineage = recorded_source_sha(current, project_id) if current else ""
        if lineage and recorded_source_sha(dict(row), project_id) == lineage:
            item_id = int(row["item_id"])
            grouped.setdefault(item_id, set()).update(
                selected[(str(row["run_id"]), item_id)]
            )
    return {item_id: frozenset(values) for item_id, values in grouped.items()}


def companion_admits_requirement(
    conn: Any, *, run_id: str, item_id: int, requirement_id: int
) -> bool:
    return requirement_id in companion_requirement_sets(
        conn, run_id=run_id, item_ids=(item_id,)
    ).get(item_id, ())
