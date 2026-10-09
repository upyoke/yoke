"""Project staging, capability and task recording retain native instant facts."""

from datetime import datetime
from uuid import uuid4

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_contracts.path_snapshot_chunks import (
    PathSnapshotChunkSyncPayload,
    PathSnapshotChunkMetadata,
)
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import project_snapshot_chunk_uploads as staging
from yoke_core.domain import projects_capabilities_settings as settings
from yoke_core.domain import projects_pulumi_state_migration_rows as pulumi
from yoke_core.domain import epic_task_sync_github_orchestrator_setup as task_history

MOMENT = parse_instant("1969-12-31T05:44:59.123456+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


def _native(value):
    assert isinstance(value, datetime) and value.utcoffset() is not None
    assert value == MOMENT


@pytest.mark.parametrize("zone", ZONES)
def test_snapshot_begin_persists_native_staging_clock(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(staging, "utc_now", lambda: MOMENT)
    staging._ensure_chunk_tables(test_db)
    payload = PathSnapshotChunkSyncPayload(
        operation="begin",
        upload_id=str(uuid4()),
        snapshot=PathSnapshotChunkMetadata(
            ref="clock-proof", commit_sha="a" * 40, file_count=0, chunk_count=0
        ),
    )
    result = staging._begin_chunk_upload(test_db, "yoke", 1, payload)
    assert result["status"] == "chunk_upload_started"
    _native(staging._load_upload(test_db, payload.upload_id)["created_at"])


@pytest.mark.parametrize("zone", ZONES)
def test_capability_creation_and_idempotent_pulumi_rows_keep_native_clock(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(settings, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(pulumi, "utc_now", lambda: MOMENT)
    settings._cas_create(
        test_db, "yoke", 1, "clock-proof", '{"evidence":"opaque clock"}'
    )
    row = test_db.execute(
        "SELECT created_at,verified_at,settings FROM project_capabilities WHERE project_id=1 AND type='clock-proof'"
    ).fetchone()
    _native(row[0])
    assert row[1] is None and row[2] == '{"evidence":"opaque clock"}'
    assert pulumi._ensure_capability_row(test_db, 1)
    assert not pulumi._ensure_capability_row(test_db, 1)
    _native(
        test_db.execute(
            "SELECT created_at FROM project_capabilities WHERE project_id=1 AND type=%s",
            (pulumi.CAPABILITY_TYPE,),
        ).fetchone()[0]
    )


@pytest.mark.parametrize("zone", ZONES)
def test_task_creation_history_uses_native_fact(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(task_history, "utc_now", lambda: MOMENT)
    item = test_db.execute("SELECT COALESCE(MAX(id),0)+1 FROM items").fetchone()[0]
    insert_item(
        test_db, id=item, workflow_id="epic", status="implementing", project="yoke"
    )
    insert_epic_task(
        test_db,
        epic_id=str(item),
        task_num=1,
        title="Clock recording",
        status="planned",
    )
    task_history.record_created_task_history(test_db, str(item), 1)
    row = test_db.execute(
        "SELECT created_at,note FROM epic_task_history WHERE epic_id=%s AND task_num=1",
        (item,),
    ).fetchone()
    _native(row[0])
    assert row[1] == "Created via sync"


def test_naive_capability_creation_clock_refuses_before_insert(test_db, monkeypatch):
    monkeypatch.setattr(settings, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(InvalidInstant):
        settings._cas_create(test_db, "yoke", 1, "clock-proof", "{}")
    assert (
        test_db.execute(
            "SELECT 1 FROM project_capabilities WHERE project_id=1 AND type='clock-proof'"
        ).fetchone()
        is None
    )
