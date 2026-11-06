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

from yoke_core.domain.deployment_run_composition_freeze import (
    items_requiring_release_membership,
)

from yoke_core.domain.deployment_run_membership_removals import (
    membership_removals,
)

from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_remove_item,
)

from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

from yoke_core.domain.flow_create import cmd_create

RELEASE_FLOW = "skipped-composition-release-flow"

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

LANDED_ITEM_ID = 9741


def _carried_dash_landing(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, status: str
) -> str:
    """One landed Dash inside the candidate's carried range, at *status*."""
    insert_item(
        conn,
        id=LANDED_ITEM_ID,
        project_sequence=LANDED_ITEM_ID,
        workflow_id="dash",
        status=status,
        deployment_flow=RELEASE_FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, LANDED_ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_landing_receipt(conn, LANDED_ITEM_ID, branch=ref, tip=landing)
    stage_environment(conn)
    cmd_create(
        conn, RELEASE_FLOW, "yoke", RELEASE_FLOW, "", RELEASE_STAGES, status="disabled"
    )
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=RELEASE_FLOW
    )
    insert_run(
        conn, "run-candidate", lineage=landing, status="created", flow=RELEASE_FLOW
    )
    return ref


def _members(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate'"
    ).fetchall()
    return [int(dict(row)["item_id"]) for row in rows]
