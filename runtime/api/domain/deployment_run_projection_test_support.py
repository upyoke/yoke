# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from datetime import datetime, timedelta

from yoke_contracts.timestamps import parse_instant

import pytest

from yoke_core.domain.deployment_run_projection import (
    DeploymentRunProjectionCollision,
    DeploymentRunProjectionError,
    normalize_snapshot,
    project_snapshot,
    snapshot_digest,
)

from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

RUN_ID = "run-20260730-901"


def _flow(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-07-30T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status"
        ") VALUES ('projected-stage',1,'Projected Stage','', '[]',"
        "'2026-07-30T00:00:00Z','disabled')"
    )
    conn.commit()


def _snapshot(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": RUN_ID,
        "project": "yoke",
        "flow": "projected-stage",
        "target_tier": "persistent",
        "target_environment": "stage",
        "release_lineage": "git:49f55781b",
        "status": "succeeded",
        "current_stage": "complete",
        "created_at": "2026-07-30T00:01:00Z",
        "started_at": "2026-07-30T00:02:00Z",
        "completed_at": "2026-07-30T00:03:00Z",
        "created_by": "release-control-plane",
        "carried_work": {"schema": 2, "items": [], "commits": []},
        "bound_sources": {"schema": 1, "projects": [], "inputs": {}},
        "artifact_identity": '{"digest":"sha256:abc"}',
        "composition_resolution": "first governed release baseline",
        "composition_frozen_at": "2026-07-30T00:01:30Z",
        "requirement_snapshot": '{"schema":1,"selections":[]}',
    }
    row.update(overrides)
    assert set(row) == set(RUN_FIELDS)
    return row
