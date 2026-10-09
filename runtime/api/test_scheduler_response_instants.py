"""Actual API projections own canonical nullable scheduler clock leaves."""

import json

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.api.routes import deploy
from yoke_core.api.main_models import FrontierItemModel, ScheduledStepModel
from yoke_core.domain.frontier_types import AdapterCategory, FrontierItem
from yoke_core.domain.scheduler_types import NextStep, ScheduledStep

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CLOCKS = (INSTANT, "2026-10-09T20:45:00.123456+05:45", None)


@pytest.mark.parametrize("clock", CLOCKS)
def test_frontier_api_projection_formats_native_clock_only(clock):
    item = FrontierItem(
        item_id=7,
        title="opaque title",
        status="implementing",
        priority="high",
        project="opaque project",
        workflow_id="opaque workflow",
        workflow_version_id=1,
        workflow_version=1,
        stage_index=1,
        adapter=AdapterCategory.CONDUCT,
        created_at=clock,
    )
    payload = json.loads(deploy._frontier_item_to_model(item).model_dump_json())
    assert payload["created_at"] == (None if clock is None else WIRE)
    assert payload["item_id"] == "7"
    assert payload["title"] == "opaque title"
    assert item.created_at == (None if clock is None else INSTANT)
    assert FrontierItemModel.model_validate(payload).created_at == payload["created_at"]


@pytest.mark.parametrize("clock", CLOCKS)
def test_scheduler_api_projection_formats_native_clock_only(clock):
    step = ScheduledStep(
        item_id=7,
        title="opaque title",
        status="implementing",
        priority="high",
        workflow_id="opaque workflow",
        workflow_version_id=1,
        workflow_version=1,
        next_step=NextStep.IMPLEMENT,
        created_at=clock,
    )
    payload = json.loads(deploy._scheduled_step_to_model(step).model_dump_json())
    assert payload["created_at"] == (None if clock is None else WIRE)
    assert payload["title"] == "opaque title"
    assert payload["item_id"] == "7"
    assert step.created_at == (None if clock is None else INSTANT)
    assert (
        ScheduledStepModel.model_validate(payload).created_at == payload["created_at"]
    )
