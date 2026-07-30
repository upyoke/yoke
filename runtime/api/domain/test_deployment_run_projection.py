"""Faithful deployment-run snapshot projection contracts."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain.deployment_run_projection import (
    DeploymentRunProjectionCollision,
    project_snapshot,
    snapshot_digest,
)
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS


RUN_ID = "run-20260730-901"


def _flow(conn: Any) -> None:
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
        "target_env": "stage",
        "release_lineage": "git:49f55781b",
        "status": "succeeded",
        "current_stage": "complete",
        "created_at": "2026-07-30T00:01:00Z",
        "started_at": "2026-07-30T00:02:00Z",
        "completed_at": "2026-07-30T00:03:00Z",
        "created_by": "release-control-plane",
    }
    row.update(overrides)
    assert set(row) == set(RUN_FIELDS)
    return row


def test_projection_inserts_and_exact_replay_is_unchanged(test_db: Any) -> None:
    _flow(test_db)
    source = _snapshot()

    created = project_snapshot(source, conn=test_db)
    replay = project_snapshot(source, conn=test_db)

    assert created["outcome"] == "created"
    assert replay == {
        "run_id": RUN_ID,
        "outcome": "unchanged",
        "snapshot_digest": snapshot_digest(source),
        "changed_fields": [],
    }
    row = test_db.execute(
        "SELECT status,created_at,started_at,completed_at,created_by "
        "FROM deployment_runs WHERE id=%s",
        (RUN_ID,),
    ).fetchone()
    assert tuple(row[field] for field in (
        "status", "created_at", "started_at", "completed_at", "created_by"
    )) == (
        "succeeded",
        "2026-07-30T00:01:00Z",
        "2026-07-30T00:02:00Z",
        "2026-07-30T00:03:00Z",
        "release-control-plane",
    )


def test_projection_repairs_same_identity_with_destination_digest(
    test_db: Any,
) -> None:
    _flow(test_db)
    synthetic = _snapshot(
        status="created",
        current_stage=None,
        created_at="2026-07-30T00:09:00Z",
        started_at=None,
        completed_at=None,
        created_by="synthetic projection",
    )
    project_snapshot(synthetic, conn=test_db)

    repaired = project_snapshot(
        _snapshot(),
        expected_destination_digest=snapshot_digest(synthetic),
        conn=test_db,
    )

    assert repaired["outcome"] == "updated"
    assert set(repaired["changed_fields"]) == {
        "status",
        "current_stage",
        "created_at",
        "started_at",
        "completed_at",
        "created_by",
    }


def test_projection_refuses_stale_digest_and_identity_collision(
    test_db: Any,
) -> None:
    _flow(test_db)
    source = _snapshot(status="created", current_stage=None)
    project_snapshot(source, conn=test_db)

    with pytest.raises(
        DeploymentRunProjectionCollision,
        match="destination snapshot digest",
    ):
        project_snapshot(
            _snapshot(),
            expected_destination_digest="0" * 64,
            conn=test_db,
        )
    with pytest.raises(
        DeploymentRunProjectionCollision,
        match="release_lineage",
    ):
        project_snapshot(
            _snapshot(release_lineage="git:different"),
            expected_destination_digest=snapshot_digest(source),
            conn=test_db,
        )
