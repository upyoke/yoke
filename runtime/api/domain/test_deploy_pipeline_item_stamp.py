"""Pipeline stamp caller + db_router shim refusal.

Proves the deploy-pipeline helpers address member items by integer
``items.id`` (including a non-default-project row whose public sequence
is a different number) and that ``_yoke_db`` no longer swallows a
non-zero router exit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain import deploy_pipeline_run_updates as run_updates
from yoke_core.domain.deploy_pipeline_reporting import (
    DeployPipelineCommandError,
    _set_deploy_stage,
    _yoke_db,
)
from yoke_core.domain.deployment_item_stamp import (
    DeploymentItemStampError,
    stamp_item_field,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain import yoke_function_registry


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yoke_function_registry.reset_registry_for_tests()
        register_all_handlers()
        yield db_path
        yoke_function_registry.reset_registry_for_tests()


def _scalar(db, sql, params):
    conn = connect_test_db(db)
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def test_stamp_item_field_writes_non_default_project_row(db):
    item_id = 8801
    conn = connect_test_db(db)
    try:
        insert_item(
            conn,
            id=item_id,
            project="externalwebapp",
            project_sequence=4,
            source=str(seed_human_actor(conn)),
        )
    finally:
        conn.close()

    result = stamp_item_field(item_id, "deployed_to", "prod")
    assert result["verified"] is True
    assert result["item_id"] == item_id
    assert _scalar(
        db, "SELECT deployed_to FROM items WHERE id = %s", (item_id,)
    ) == "prod"


def test_stamp_item_field_raises_when_item_missing(db):
    with pytest.raises(DeploymentItemStampError, match="items.id=40404"):
        stamp_item_field(40404, "deploy_stage", "complete")


def test_set_deploy_stage_stamps_member_then_run(db, monkeypatch):
    item_id = 8802
    conn = connect_test_db(db)
    try:
        insert_item(
            conn,
            id=item_id,
            project="externalwebapp",
            project_sequence=5,
            source=str(seed_human_actor(conn)),
        )
    finally:
        conn.close()

    seen: list[tuple[str, ...]] = []

    def _fake_update_run_field(run_id, field, value):
        seen.append((run_id, field, value))

    monkeypatch.setattr(run_updates, "update_run_field", _fake_update_run_field)
    _set_deploy_stage("warm-up", "run-20260822-001", [str(item_id)])
    assert _scalar(
        db, "SELECT deploy_stage FROM items WHERE id = %s", (item_id,)
    ) == "warm-up"
    assert seen == [
        ("run-20260822-001", "current_stage", "warm-up"),
    ]


def test_yoke_db_raises_on_nonzero(monkeypatch):
    def _fail(_cmd, timeout=60):
        return subprocess.CompletedProcess(
            args=_cmd, returncode=1, stdout="", stderr="no such item",
        )

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._run_cmd",
        _fail,
    )
    with pytest.raises(DeployPipelineCommandError, match="no such item"):
        _yoke_db("items", "update", "12", "deploy_stage", "complete")
