"""Delivery custody is an authored flow declaration, not a schema-version side effect."""

from __future__ import annotations

import importlib
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
from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    requires_release_admission,
)
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.flow_crud import cmd_update_stages

ENTRY_NAME = "0047_deployment_flow_delivery_custody"
EXECUTION_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)
ITEM_ID = 9601


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def _create(
    conn: Any,
    flow_id: str,
    stages: str,
    *,
    name: str,
    takes_delivery_custody: bool | None = None,
) -> None:
    kwargs: dict[str, Any] = {}
    if takes_delivery_custody is not None:
        kwargs["takes_delivery_custody"] = takes_delivery_custody
    cmd_create(conn, flow_id, "yoke", name, "", stages, status="disabled", **kwargs)


def _custody(conn: Any, flow_id: str) -> int:
    row = conn.execute(
        "SELECT takes_delivery_custody FROM deployment_flows WHERE id=%s",
        (flow_id,),
    ).fetchone()
    value = row["takes_delivery_custody"] if hasattr(row, "keys") else row[0]
    return int(value)


def _candidate(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flow: str
) -> str:
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow,
    )
    ref = item_ref(conn, ITEM_ID)
    repo, baseline, tip = release_repository(tmp_path, ref)
    record_landing_receipt(conn, ITEM_ID, branch=ref, tip=tip)
    serve_repository(monkeypatch, repo)
    insert_run(conn, "run-previous", lineage=baseline, status="succeeded", flow=flow)
    insert_run(conn, "run-candidate", lineage=tip, status="created", flow=flow)
    return ref


@pytest.fixture
def seeded(test_db: Any) -> Any:
    stage_environment(test_db)
    return test_db


def test_omitted_flag_takes_delivery_custody(seeded: Any) -> None:
    _create(seeded, "default-custody", EXECUTION_STAGES, name="Default custody")
    assert _custody(seeded, "default-custody") == 1


def test_execution_flow_can_decline_delivery_custody(
    seeded: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create(
        seeded,
        "without-custody",
        EXECUTION_STAGES,
        name="Without custody",
        takes_delivery_custody=False,
    )
    _candidate(seeded, tmp_path, monkeypatch, "without-custody")
    assert _custody(seeded, "without-custody") == 0
    assert requires_release_admission(seeded, "run-candidate") is False
    assert carried_enrollment_blocked(seeded, "run-candidate") == (
        "flow_without_delivery_custody"
    )
    assert enroll_carried_members(seeded, "run-candidate") == ()


def test_execution_flow_can_take_delivery_custody(
    seeded: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create(
        seeded,
        "with-custody",
        EXECUTION_STAGES,
        name="With custody",
        takes_delivery_custody=True,
    )
    ref = _candidate(seeded, tmp_path, monkeypatch, "with-custody")
    assert requires_release_admission(seeded, "run-candidate") is True
    assert enroll_carried_members(seeded, "run-candidate") == (ref,)


def test_editing_stages_does_not_change_custody(seeded: Any) -> None:
    _create(
        seeded,
        "annotate",
        EXECUTION_STAGES,
        name="Annotate",
        takes_delivery_custody=False,
    )
    assert _custody(seeded, "annotate") == 0
    stages = json.loads(EXECUTION_STAGES)
    stages[0]["name"] = "release"
    cmd_update_stages(seeded, "annotate", json.dumps(stages))
    row = seeded.execute(
        "SELECT definition_schema_version, takes_delivery_custody "
        "FROM deployment_flows WHERE id='annotate'"
    ).fetchone()
    version = row["definition_schema_version"] if hasattr(row, "keys") else row[0]
    custody = row["takes_delivery_custody"] if hasattr(row, "keys") else row[1]
    assert int(version) == 2
    assert int(custody) == 0


def test_backfill_fills_nulls_and_leaves_authored_zero(seeded: Any) -> None:
    entry = _entry()
    _create(seeded, "backfill-v2", EXECUTION_STAGES, name="Backfill v2")
    _create(
        seeded,
        "authored-zero",
        EXECUTION_STAGES,
        name="Authored zero",
        takes_delivery_custody=False,
    )
    seeded.execute(
        "ALTER TABLE deployment_flows ALTER COLUMN takes_delivery_custody DROP NOT NULL"
    )
    seeded.execute(
        "UPDATE deployment_flows SET takes_delivery_custody = NULL "
        "WHERE id='backfill-v2'"
    )
    seeded.commit()
    entry.apply(seeded)
    seeded.commit()
    entry.invariants(seeded)
    assert _custody(seeded, "backfill-v2") == 1
    assert _custody(seeded, "authored-zero") == 0


def test_backfill_adds_the_column_when_absent(seeded: Any) -> None:
    entry = _entry()
    _create(seeded, "pre-column", EXECUTION_STAGES, name="Pre column")
    seeded.execute("ALTER TABLE deployment_flows DROP COLUMN takes_delivery_custody")
    seeded.commit()
    entry.apply(seeded)
    seeded.commit()
    entry.invariants(seeded)
    assert _custody(seeded, "pre-column") == 1
