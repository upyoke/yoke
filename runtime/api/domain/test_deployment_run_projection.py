"""Faithful deployment-run snapshot projection contracts."""

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
    assert tuple(
        row[field]
        for field in (
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "created_by",
        )
    ) == (
        "succeeded",
        parse_instant("2026-07-30T00:01:00Z"),
        parse_instant("2026-07-30T00:02:00Z"),
        parse_instant("2026-07-30T00:03:00Z"),
        "release-control-plane",
    )
    carried = test_db.execute(
        "SELECT carried_work,bound_sources FROM deployment_runs WHERE id=%s",
        (RUN_ID,),
    ).fetchone()
    assert '"schema":2' in carried["carried_work"]
    # The commits a run pinned for other projects project alongside its own.
    assert '"projects":[]' in carried["bound_sources"]


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


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_projection_uses_native_instants_for_replay_and_microsecond_cas(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    _flow(test_db)
    stamp = parse_instant("1969-12-31T23:59:59.999999Z")
    opaque = ' \n{"clock":"1969-12-31T18:59:59.999999-05:00"}\n '
    source = _snapshot(
        created_at=stamp,
        started_at=None,
        completed_at=stamp,
        composition_frozen_at=stamp,
        requirement_snapshot=opaque,
    )
    equivalent = {**source, "created_at": "1970-01-01T05:29:59.999999+05:30"}
    assert snapshot_digest(source) == snapshot_digest(equivalent)
    created = project_snapshot(source, conn=test_db)
    assert project_snapshot(equivalent, conn=test_db)["outcome"] == "unchanged"
    assert source["created_at"] == stamp and source["requirement_snapshot"] == opaque
    raw = test_db.execute(
        "SELECT created_at,started_at,completed_at,composition_frozen_at,"
        "requirement_snapshot FROM deployment_runs WHERE id=%s",
        (RUN_ID,),
    ).fetchone()
    assert tuple(raw) == (stamp, None, stamp, stamp, opaque)
    updated = {**source, "completed_at": stamp + timedelta(microseconds=1)}
    repaired = project_snapshot(
        updated, expected_destination_digest=created["snapshot_digest"], conn=test_db
    )
    assert repaired["changed_fields"] == ["completed_at"]
    with pytest.raises(
        DeploymentRunProjectionCollision, match="destination snapshot digest"
    ):
        project_snapshot(
            source, expected_destination_digest=created["snapshot_digest"], conn=test_db
        )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
        0,
        datetime(1970, 1, 1),
    ],
)
def test_projection_refuses_invalid_owned_clock_before_database_access(bad):
    with pytest.raises(DeploymentRunProjectionError, match="invalid_instant"):
        project_snapshot(_snapshot(started_at=bad), conn=object())
    assert normalize_snapshot(_snapshot(started_at=None))["started_at"] is None
