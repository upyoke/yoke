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
        "wait_for_ci": True,
    }
    stage.update(overrides)
    return stage


def _route(*stages):
    return [{"name": "merged", "step_runner": "auto"}, *stages]


WARM_UP = {"name": "warm-up", "step_runner": "warm-up", "connection_env": "prod"}


class _Conn:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("doctor must use registered reads, not local SQL")


@pytest.fixture(params=["database", "https"])
def transport(request):
    return request.param


def _run(monkeypatch, flows, *, production=True, transport="https"):
    calls = []

    def read(function_id, payload):
        calls.append((function_id, payload))
        if function_id == "deployment_flows.list":
            assert payload == {"project": "acme"}
            return {"rows": [
                {"id": flow_id, "stages": json.dumps(stages),
                 "target_environment": "live"}
                for flow_id, stages in flows.items()
            ]}
        assert function_id == "projects.environment_settings.get"
        assert payload == {
            "project": "acme", "environment": "live",
            "paths": ["role.production"],
        }
        return {"values": {"role.production": production}}

    monkeypatch.setattr(mod, "relay", read)
    records = RecordCollector()
    from yoke_core.engines.doctor_https_compose import UnavailableControlPlane
    conn = UnavailableControlPlane() if transport == "https" else _Conn()
    mod.hc_hosted_route_stage_contract(conn, DoctorArgs(project="acme"), records)
    assert len(records.results) == 1
    assert calls[0][0] == "deployment_flows.list"
    return records.results[0]


def test_passes_for_a_route_that_carries_the_whole_contract(monkeypatch, transport) -> None:
    result = _run(
        monkeypatch, {"acme-prod": _route(_dispatch_stage(), WARM_UP)},
        transport=transport,
    )

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
        ({"wait_for_ci": False}, "production per-commit CI gate"),
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


def test_omitted_warm_up_connection_follows_the_run_target(monkeypatch) -> None:
    warm = {"name": "warm-up", "step_runner": "warm-up"}
    result = _run(monkeypatch, {"acme-prod": _route(_dispatch_stage(), warm)})

    assert result.result == "PASS"


@pytest.mark.parametrize("production, mode", [(True, "hotfix"), (False, "normal")])
def test_stage_and_hotfix_allow_skipping_ci(monkeypatch, transport, production, mode):
    stage = _dispatch_stage(
        wait_for_ci=False,
        inputs={"target_environment": "{target_environment}", "release_mode": mode},
    )
    result = _run(
        monkeypatch, {"acme-release": _route(stage, WARM_UP)},
        production=production, transport=transport,
    )
    assert result.result == "PASS"


def test_production_without_ci_fails_on_both_transports(monkeypatch, transport):
    result = _run(
        monkeypatch,
        {"acme-release": _route(_dispatch_stage(wait_for_ci=False), WARM_UP)},
        transport=transport,
    )
    assert result.result == "FAIL"
    assert "wait_for_ci is not true" in result.detail


def test_unreadable_flows_fail_with_recovery(monkeypatch):
    def refused(*_args):
        raise RuntimeError("control plane unavailable")
    monkeypatch.setattr(mod, "relay", refused)
    rec = RecordCollector()
    mod.hc_hosted_route_stage_contract(None, DoctorArgs(project="acme"), rec)
    assert rec.results[0].result == "FAIL"
    assert "control plane unavailable" in rec.results[0].detail
    assert "yoke deployment-flows list" in rec.results[0].detail


def test_missing_production_declaration_fails(monkeypatch):
    result = _run(
        monkeypatch, {"acme-prod": _route(_dispatch_stage(), WARM_UP)},
        production=None,
    )
    assert result.result == "FAIL"
    assert "role.production" in result.detail
