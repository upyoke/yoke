"""Deployment run events are written once per run, never once per member."""

from __future__ import annotations

from collections import Counter
from unittest import mock

import pytest

from yoke_core.api import service_client_structured_api_adapter as adapter
from yoke_core.domain import (
    deploy_pipeline_events,
    deploy_pipeline_failure,
    deploy_pipeline_run_updates as run_updates,
)

MEMBERS = ["YOK-1", "YOK-2", "YOK-3"]


@pytest.fixture
def emitted(monkeypatch) -> list[dict]:
    payloads: list[dict] = []

    def fake_call_dispatcher(*, function_id, target, payload, **_):
        assert function_id == "events.emit"
        assert target.kind == "global"
        payloads.append(payload)

    monkeypatch.setattr(adapter, "call_dispatcher", fake_call_dispatcher)
    return payloads


def test_stage_event_is_one_run_level_event(emitted) -> None:
    context = {"run_id": "run-1", "stage": "warm-up"}
    for name in ("DeploymentRunStageStarted", "DeploymentRunStageCompleted"):
        deploy_pipeline_events.emit_run_event(
            name, "completed", context, project="yoke"
        )

    assert [p["name"] for p in emitted] == [
        "DeploymentRunStageStarted",
        "DeploymentRunStageCompleted",
    ]
    for payload in emitted:
        assert payload["context"]["run_id"] == "run-1"
        assert payload["type"] == "deployment_run"
        assert "public_ref" not in payload


def test_failed_stage_on_multi_member_run_writes_each_event_once(emitted) -> None:
    with (
        mock.patch.object(deploy_pipeline_failure.reporting, "_set_deploy_stage"),
        mock.patch.object(run_updates, "update_run_field"),
        mock.patch.object(deploy_pipeline_failure, "_report_failure_trace"),
    ):
        deploy_pipeline_failure.fail_pipeline_stage(
            exit_code=1,
            diagnostic="",
            stage_name="hosted-release",
            run_id="run-1",
            flow_id="flow",
            member_items=MEMBERS,
            project="yoke",
            sd=None,
            emit_event=deploy_pipeline_events.emit_run_event,
        )

    assert Counter(p["name"] for p in emitted) == {
        "DeploymentRunStageFailed": 1,
        "DeploymentRunFailed": 1,
    }
    assert all("public_ref" not in p for p in emitted)
