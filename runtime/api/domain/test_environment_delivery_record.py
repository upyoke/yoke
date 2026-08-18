"""Create-time environment resolution and last_deployed_at stamping."""

from __future__ import annotations

from pathlib import Path

from runtime.api.deployment_runs_test_db import _apply_schema
from runtime.api.fixtures.file_test_db import (
    connect_test_db,
    init_test_db,
)
import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.environment_delivery_record import UnregisteredEnvironment


@pytest.fixture
def delivery_db(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as token:
        yield token


def test_create_run_refuses_unregistered_environment(delivery_db) -> None:
    with pytest.raises(UnregisteredEnvironment, match="registered:"):
        dr.cmd_create_run(
            "yoke", "flow-main", environment="sandbox", db_path=delivery_db,
        )


def test_create_run_accepts_registered_name(delivery_db) -> None:
    named = dr.cmd_create_run(
        "yoke", "flow-main", environment="prod", db_path=delivery_db,
    )
    assert named.startswith("run-")


def test_override_keeps_operator_reads_name_only(delivery_db) -> None:
    run_id = dr.cmd_create_run(
        "yoke", "flow-main", environment="prod", db_path=delivery_db,
    )
    stored = dr.cmd_get(
        run_id, field="target_environment", db_path=delivery_db,
    )
    assert stored == "prod"
    conn = connect_test_db(delivery_db)
    try:
        internal = conn.execute(
            "SELECT target_environment_id FROM deployment_runs WHERE id = %s",
            (run_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert internal == 201


def test_succeeded_run_stamps_last_deployed_at(delivery_db) -> None:
    run_id = dr.cmd_create_run(
        "yoke", "flow-main", environment="prod", db_path=delivery_db,
    )
    assert dr.cmd_update(run_id, "status", "succeeded", db_path=delivery_db) is None
    conn = connect_test_db(delivery_db)
    try:
        stamped = conn.execute(
            "SELECT last_deployed_at FROM environments WHERE id = %s",
            (201,),
        ).fetchone()
    finally:
        conn.close()
    assert stamped is not None
    assert stamped[0]


def test_merge_only_flow_carries_no_environment(delivery_db) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-preview", db_path=delivery_db)
    assert run_id.startswith("run-")
    assert dr.cmd_get(
        run_id, field="target_environment", db_path=delivery_db,
    ) == ""
