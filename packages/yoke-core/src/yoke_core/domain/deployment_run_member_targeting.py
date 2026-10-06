"""Admission and custody for releases that answer different item QA targets."""

from __future__ import annotations

import json
from typing import Any


def supplemental_qa_run(conn: Any, *, run_id: str, item_id: int) -> bool:
    """A different persistent environment proves QA without final delivery.

    The completion flow remains the delivery authority. This works for an
    own-project run and for a run carrying another project's bound source.
    """
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow

    flow = item_completion_flow(conn, int(item_id))
    row = conn.execute(
        "SELECT re.name, ce.name FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        "LEFT JOIN deployment_flows cf ON cf.id=%s "
        "LEFT JOIN environments re ON re.id=COALESCE(dr.target_environment_id, df.target_environment_id) "
        "LEFT JOIN environments ce ON ce.id=cf.target_environment_id WHERE dr.id=%s",
        (flow, str(run_id)),
    ).fetchone()
    return bool(row and row[0] and row[1] and str(row[0]) != str(row[1]))


def targeted_requirement_ids(conn: Any, *, run_id: str, item_id: int) -> frozenset[int]:
    """Explicit obligations this run can answer, including on a second target."""
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        outstanding_post_deploy_requirements,
        run_qa_stage_targets,
        stage_target_admits,
    )

    environments, dynamic = run_qa_stage_targets(conn, run_id)
    return frozenset(
        row["id"]
        for row in outstanding_post_deploy_requirements(conn, item_id)
        if row["target_env"]
        and stage_target_admits(
            row["target_env"], environments=environments, dynamic=dynamic
        )
    )


def run_needs_member(conn: Any, *, run_id: str, item_id: int) -> bool:
    """Supplemental releases enroll only members owing their explicit target."""
    return not supplemental_qa_run(conn, run_id=run_id, item_id=item_id) or bool(
        targeted_requirement_ids(conn, run_id=run_id, item_id=item_id)
    )


def holder_covers_run(conn: Any, *, holder_id: str, run_id: str, item_id: int) -> bool:
    """A holder of stage proof cannot reserve the production delivery, or vice versa."""
    if not supplemental_qa_run(conn, run_id=run_id, item_id=item_id) and (
        supplemental_qa_run(conn, run_id=holder_id, item_id=item_id)
    ):
        return False
    wanted = targeted_requirement_ids(conn, run_id=run_id, item_id=item_id)
    covered = member_selected_requirement_ids(conn, run_id=holder_id, item_id=item_id)
    return wanted <= covered


def member_selected_requirement_ids(
    conn: Any, *, run_id: str, item_id: int
) -> frozenset[int]:
    """Frozen selection outranks target capability when a member already exists."""
    row = conn.execute(
        "SELECT requirement_snapshot, requirement_selection FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (run_id, int(item_id)),
    ).fetchone()
    if row and row[0]:
        snapshot = json.loads(str(row[0]))
        return frozenset(int(entry["id"]) for entry in snapshot["requirements"])
    if row and row[1]:
        from yoke_core.domain.deployment_requirement_snapshots import (
            snapshot_member_requirements,
        )

        snapshot = json.loads(
            snapshot_member_requirements(
                conn,
                run_id=run_id,
                item_id=item_id,
                selection_json=str(row[1]),
            )
        )
        return frozenset(int(entry["id"]) for entry in snapshot["requirements"])
    return targeted_requirement_ids(conn, run_id=run_id, item_id=item_id)


def companion_admits_requirement(
    conn: Any, *, run_id: str, item_id: int, requirement_id: int
) -> bool:
    """A composed sibling at the same project revision already owns this proof."""
    from yoke_core.domain.deployment_run_project_sources import run_source_sha

    project = conn.execute(
        "SELECT project_id FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if project is None:
        return False
    lineage = run_source_sha(conn, run_id, int(project[0]))
    if not lineage:
        return False
    rows = conn.execute(
        "SELECT dr.id FROM deployment_runs dr JOIN deployment_run_items dri ON dri.run_id=dr.id "
        "WHERE dri.item_id=%s AND dr.id <> %s AND dr.status IN ('created','executing','succeeded')",
        (int(item_id), run_id),
    ).fetchall()
    return any(
        run_source_sha(conn, str(row[0]), int(project[0])) == lineage
        and requirement_id
        in member_selected_requirement_ids(conn, run_id=str(row[0]), item_id=item_id)
        for row in rows
    )
