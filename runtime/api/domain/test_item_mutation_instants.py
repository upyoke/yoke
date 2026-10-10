"""Item mutation clocks retain precision through native SQL bindings."""

import json
from datetime import datetime

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant, temporal_wire
from yoke_core.domain import backlog_item_db_writes, mutations_create, mutations_update
from yoke_core.domain.mutation_fields import ApprovalResult, ItemState
from yoke_core.domain.runs import DeploymentRun, RunItem
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


def test_prepared_item_mutations_retain_native_clocks(monkeypatch):
    workflow = builtin_workflow_runtime("dash")
    monkeypatch.setattr(mutations_create, "utc_now", lambda: STAMP)
    monkeypatch.setattr(mutations_update, "utc_now", lambda: STAMP)
    created = mutations_create.prepare_create(
        title="Native clock", workflow=workflow, project="yoke"
    )
    assert created.success
    assert (
        created.field_writes["created_at"]
        == created.field_writes["updated_at"]
        == STAMP
    )
    item = ItemState(
        id=7,
        title="Native clock",
        status=workflow.stage_ids[0],
        priority="medium",
        project="yoke",
        workflow=workflow,
    )
    updated = mutations_update.prepare_update(
        item=item, field_name="title", value="Updated clock"
    )
    assert updated.success
    assert updated.field_writes["updated_at"] == STAMP


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_backlog_clock_writes_are_native_and_nullable(test_db, monkeypatch, zone):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    monkeypatch.setattr(backlog_item_db_writes, "_now_iso", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    backlog_item_db_writes._update_item_multi(
        test_db,
        7,
        {"created_at": "1970-01-01T05:29:59.123456+05:30", "spec_updated_at": None},
    )
    row = test_db.execute(
        "SELECT created_at, updated_at, spec_updated_at FROM items WHERE id=7"
    ).fetchone()
    assert tuple(row) == (STAMP, STAMP, None)
    backlog_item_db_writes._update_item_field(test_db, 7, "spec_updated_at", STAMP)
    assert (
        test_db.execute("SELECT spec_updated_at FROM items WHERE id=7").fetchone()[0]
        == STAMP
    )


def test_invalid_declared_clock_refuses_before_item_write(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    before = tuple(
        test_db.execute(
            "SELECT created_at, updated_at FROM items WHERE id=7"
        ).fetchone()
    )
    with pytest.raises(ValueError):
        backlog_item_db_writes._update_item_multi(
            test_db, 7, {"created_at": "2026-10-08 12:34:56"}
        )
    assert (
        tuple(
            test_db.execute(
                "SELECT created_at, updated_at FROM items WHERE id=7"
            ).fetchone()
        )
        == before
    )


@pytest.mark.parametrize(
    "value",
    [
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
        "1969-12-31T19:59:59.123456-04:00",
    ],
)
def test_run_and_mutation_models_retain_native_clock_facts(value):
    from yoke_core.api.service_client_shared_emit import _mutation_result_to_dict

    run = DeploymentRun(
        "run",
        "project",
        "flow",
        "executing",
        created_at=value,
        started_at=value,
        completed_at=value,
    )
    member = RunItem("run", 7, added_at=value)
    item = ItemState(7, "item", "implementing", "medium", merged_at=value)
    approval = ApprovalResult(
        success=True,
        approved_at=value,
        field_writes={"updated_at": STAMP, "opaque": value},
    )
    assert run.created_at == run.started_at == run.completed_at == STAMP
    assert member.added_at == item.merged_at == approval.approved_at == STAMP
    assert json.loads(json.dumps(temporal_wire({"added_at": member.added_at}))) == {
        "added_at": "1969-12-31T23:59:59.123456Z",
    }
    wire = json.loads(json.dumps(_mutation_result_to_dict(approval)))
    assert (
        wire["approved_at"]
        == wire["field_writes"]["updated_at"]
        == "1969-12-31T23:59:59.123456Z"
    )
    assert wire["field_writes"]["opaque"] == value
    assert approval.field_writes["updated_at"] == STAMP


def test_run_and_mutation_models_preserve_absent_clock_facts():
    run = DeploymentRun("run", "project", "flow", "created")
    assert run.created_at is run.started_at is run.completed_at is None
    assert RunItem("run", 7).added_at is None
    assert ItemState(7, "item", "implementing", "medium").merged_at is None
    assert ApprovalResult(success=False).approved_at is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
        datetime(1970, 1, 1),
    ],
)
def test_run_and_mutation_models_refuse_unverifiable_clock_facts(value):
    for field in ("created_at", "started_at", "completed_at"):
        with pytest.raises(InvalidInstant):
            DeploymentRun("run", "project", "flow", "created", **{field: value})
    with pytest.raises(InvalidInstant):
        RunItem("run", 7, added_at=value)
    with pytest.raises(InvalidInstant):
        ItemState(7, "item", "implementing", "medium", merged_at=value)
    with pytest.raises(InvalidInstant):
        ApprovalResult(success=True, approved_at=value)
