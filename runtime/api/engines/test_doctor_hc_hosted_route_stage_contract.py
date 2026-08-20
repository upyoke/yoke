"""Tests for HC-hosted-route-stage-contract."""

from __future__ import annotations

import json

import pytest

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_hosted_route_stage_contract as mod


def _dispatch_stage(**overrides):
    stage = {
        "name": "hosted-release",
        "step_runner": "github-actions-workflow",
        "workflow": "release-bridge.yml",
        "dispatch_correlation_input": "yoke_dispatch_id",
        "inputs": {"target_environment": "{target_environment}"},
        "reconcile_by_head_sha": False,
        "wait_for_ci": False,
    }
    stage.update(overrides)
    return stage


def _route(*stages):
    return [{"name": "merged", "step_runner": "auto"}, *stages]


WARM_UP = {"name": "warm-up", "step_runner": "warm-up", "connection_env": "prod"}


class _Conn:
    def __init__(self, flows):
        self._flows = flows

    def execute(self, sql, params=()):  # noqa: ARG002 - shape only
        return self

    def fetchall(self):
        return [
            {"id": flow_id, "stages": json.dumps(stages)}
            for flow_id, stages in self._flows.items()
        ]

    def fetchone(self):
        return (1,)


def _run(monkeypatch, flows):
    monkeypatch.setattr(mod._base, "_table_exists", lambda conn, name: True)
    monkeypatch.setattr(
        mod, "query_rows",
        lambda conn, sql, params=(): conn.fetchall(),
    )
    records = RecordCollector()
    mod.hc_hosted_route_stage_contract(_Conn(flows), DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_passes_for_a_route_that_carries_the_whole_contract(monkeypatch) -> None:
    result = _run(monkeypatch, {"acme-prod": _route(_dispatch_stage(), WARM_UP)})

    assert result.result == "PASS"
    assert "1 active dispatching route(s)" in result.detail


def test_passes_when_no_route_dispatches_a_workflow(monkeypatch) -> None:
    result = _run(
        monkeypatch,
        {"acme-internal": [{"name": "merged", "step_runner": "auto"}]},
    )

    assert result.result == "PASS"
    assert "no active workflow-dispatching route" in result.detail


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"dispatch_correlation_input": None}, "dispatch_correlation_input"),
        ({"reconcile_by_head_sha": True}, "reuse an older run"),
        ({"wait_for_ci": True}, "waits on CI"),
        (
            {"inputs": {"target_environment": "prod"}},
            "instead of the {target_environment} placeholder",
        ),
    ],
)
def test_fails_when_the_dispatch_stage_breaks_its_contract(
    monkeypatch, override, expected,
) -> None:
    result = _run(
        monkeypatch,
        {"acme-prod": _route(_dispatch_stage(**override), WARM_UP)},
    )

    assert result.result == "FAIL"
    assert expected in result.detail
    assert "yoke deployment-flows set-status" in result.detail


def test_fails_when_the_route_never_warms_the_box_it_rolls(monkeypatch) -> None:
    result = _run(monkeypatch, {"acme-prod": _route(_dispatch_stage())})

    assert result.result == "FAIL"
    assert "never warms the box it rolls" in result.detail


def test_fails_when_the_route_warms_before_it_rolls(monkeypatch) -> None:
    result = _run(monkeypatch, {"acme-prod": _route(WARM_UP, _dispatch_stage())})

    assert result.result == "FAIL"
    assert "warms before it rolls" in result.detail


def test_fails_when_the_warm_up_names_no_connection(monkeypatch) -> None:
    warm = {"name": "warm-up", "step_runner": "warm-up"}
    result = _run(monkeypatch, {"acme-prod": _route(_dispatch_stage(), warm)})

    assert result.result == "FAIL"
    assert "names no connection_env" in result.detail
