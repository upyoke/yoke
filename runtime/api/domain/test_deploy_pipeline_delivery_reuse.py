"""The driver skips a workflow dispatch only when the control plane reuses it."""

from __future__ import annotations

import pytest

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deploy_pipeline_stage_receipt as stage_receipt

STAGE = {
    "name": "hosted-release",
    "step_runner": "github-actions-workflow",
    "workflow": "platform-release-bridge.yml",
    "input_bindings": {"consumer_sha": {"project": "platform", "branch": "main"}},
}


@pytest.fixture
def dispatched(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(stage_receipt, "driver_source_drift_refusal", lambda _l: "")

    def _dispatch(stage, **_kwargs):
        calls.append(stage["name"])
        return 0, ""

    monkeypatch.setattr(stage_receipt, "_dispatch_step_runner", _dispatch)
    return calls


def _run(stage=STAGE, *, fresh=False):
    return stage_receipt.dispatch_step_runner_with_receipt(
        stage,
        stages=[stage],
        run_id="run-reuse",
        member_items=[],
        github_repo="owner/repo",
        project="yoke",
        project_repo_path="/repo",
        branch="main",
        first_item="YOK-1",
        timeout_min=5,
        fresh=fresh,
        gate_branch="main",
        release_lineage="a" * 40,
    )


def _answer(monkeypatch, answer):
    asked: list[str] = []

    def _reuse(run_id, *, stage_name):
        asked.append(stage_name)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(control_plane, "reuse_delivery", _reuse)
    return asked


def test_reused_delivery_completes_without_dispatch(monkeypatch, dispatched, capsys):
    _answer(monkeypatch, {"reused_run_id": "run-served", "reason": ""})
    assert _run() == (0, "stage 'hosted-release' reused the delivery of run run-served")
    assert dispatched == []
    assert "reuses the delivery of run run-served" in capsys.readouterr().out


def test_declined_reuse_dispatches_and_says_why(monkeypatch, dispatched, capsys):
    _answer(monkeypatch, {"reused_run_id": "", "reason": "product changed"})
    assert _run() == (0, "")
    assert dispatched == ["hosted-release"]
    assert "dispatches: product changed" in capsys.readouterr().out


def test_unserved_reuse_function_dispatches_as_before(monkeypatch, dispatched, capsys):
    _answer(
        monkeypatch,
        control_plane.DeploymentControlPlaneError("skew", code="function_version_skew"),
    )
    assert _run() == (0, "")
    assert dispatched == ["hosted-release"]
    assert "minimum serving version next-release" in capsys.readouterr().err


def test_other_reuse_refusal_stops_the_stage(monkeypatch, dispatched):
    _answer(
        monkeypatch,
        control_plane.DeploymentControlPlaneError("refused", code="delivery_reuse_refused"),
    )
    with pytest.raises(control_plane.DeploymentControlPlaneError):
        _run()
    assert dispatched == []


@pytest.mark.parametrize(
    "stage,fresh",
    [
        (STAGE, True),
        ({k: v for k, v in STAGE.items() if k != "input_bindings"}, False),
        ({"name": "warm-up", "step_runner": "warm-up"}, False),
    ],
)
def test_fresh_and_unbound_stages_never_ask(monkeypatch, dispatched, stage, fresh):
    asked = _answer(monkeypatch, {"reused_run_id": "run-served", "reason": ""})
    assert _run(stage, fresh=fresh) == (0, "")
    assert asked == []
    assert dispatched == [stage["name"]]
