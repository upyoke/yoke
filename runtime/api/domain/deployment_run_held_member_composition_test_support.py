# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)

from yoke_core.domain.deployment_member_run_coverage import (
    unclosable_final_member_refusal,
)

from yoke_core.domain.deployment_run_carried_membership import (
    enroll_carried_members,
)

from yoke_core.domain.deployment_run_carried_work import derive_carried_work

from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody

from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

from yoke_core.domain.flow_create import cmd_create

CARRIER_FLOW = "held-member-carrier-flow"

HOLDER_FLOW = "held-member-holder-flow"

RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)

LANDED_ITEM_ID = 9731


def _final_delivery(conn: Any, *run_ids: str) -> None:
    """Make each run the persistent-tier release that owes its members done.

    The prior release needs the same target environment as the candidate: the
    carried range's baseline is the last succeeded run of THAT environment, so
    tiering only the candidate would leave it with no range at all.
    """
    environment = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for run_id in run_ids:
        conn.execute(
            "UPDATE deployment_runs SET target_tier='persistent',"
            "target_environment_id=%s WHERE id=%s",
            (environment, run_id),
        )
    conn.commit()


def _carried_landing(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item_flow: str,
) -> str:
    """One delivery-ready landing inside the new candidate's carried range."""
    insert_item(
        conn,
        id=LANDED_ITEM_ID,
        project_sequence=LANDED_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=item_flow,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, LANDED_ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_landing_receipt(conn, LANDED_ITEM_ID, branch=ref, tip=landing)
    stage_environment(conn)
    for flow in (CARRIER_FLOW, HOLDER_FLOW):
        cmd_create(conn, flow, "yoke", flow, "", RELEASE_STAGES, status="disabled")
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=CARRIER_FLOW
    )
    insert_run(
        conn, "run-candidate", lineage=landing, status="created", flow=CARRIER_FLOW
    )
    _final_delivery(conn, "run-previous", "run-candidate")
    return ref


def _holder(conn: Any, run_id: str, *, status: str, flow: str = HOLDER_FLOW) -> None:
    """A second run that named this item and pinned the same landing."""
    lineage = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    insert_run(conn, run_id, lineage=lineage, status=status, flow=flow)
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES (%s,%s,'2026-09-14T00:30:00Z')",
        (run_id, LANDED_ITEM_ID),
    )
    conn.commit()


def _members(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate' "
        "ORDER BY item_id"
    ).fetchall()
    return [int(dict(row)["item_id"]) for row in rows]
