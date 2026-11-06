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

from yoke_core.domain.deployment_run_create_write import (
    CompositionRefused,
    create_run,
)

from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

from yoke_core.domain.flow_create import cmd_create

RELEASE_FLOW = "stranded-dependents-flow"


def _candidate(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statuses: dict[int, str],
) -> tuple[dict[int, str], str]:
    """Dash items carried by one landing, and the candidate commit."""
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        json.dumps(
            [
                {
                    "name": "stage",
                    "step_runner": "auto",
                    "stage_kind": "execution",
                    "scope": "run",
                }
            ]
        ),
        target_tier="ephemeral",
    )
    for item_id, status in statuses.items():
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status=status,
            deployment_flow=RELEASE_FLOW,
            merged_at="2026-09-14T00:10:00Z",
        )
    conn.commit()
    refs = {item_id: item_ref(conn, item_id) for item_id in statuses}
    repo, baseline, tip = release_repository(tmp_path, "stranded")
    for item_id, ref in refs.items():
        record_landing_receipt(conn, item_id, branch=ref, tip=tip)
    serve_repository(monkeypatch, repo)
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=RELEASE_FLOW
    )
    return refs, tip
