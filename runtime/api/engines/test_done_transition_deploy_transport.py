"""Transport-aware routing regression tests for the deployment guards.

The done-transition deployment guards must route their control-plane reads
through ``call_dispatcher`` so the merge finalize deploy checks run over an
https control plane. These tests monkeypatch ``call_dispatcher`` and assert
every deployment read relays instead of opening a bare ``_connect()``, with
each guard's verdict and narrative preserved. The guards fail closed: a
refused read raises so the transition never proceeds on unread evidence.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition as dt
from yoke_core.engines import done_transition_deploy_gates as deploy_gates


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _install(monkeypatch, fake):
    monkeypatch.setattr(deploy_gates, "call_dispatcher", fake)
    monkeypatch.setattr(
        dt, "_connect",
        lambda *a, **k: pytest.fail("must not open a bare _connect() on a read path"),
    )


def _router(responses):
    """Return a fake dispatcher keyed by function id (defaults to success)."""
    def fake(**kwargs):
        fid = kwargs["function_id"]
        if fid in responses:
            return responses[fid]
        return _resp(fid)
    return fake


class TestDeploymentEvidence:
    def test_succeeded_is_true(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.latest_deployment_run":
                _resp("done_transition.latest_deployment_run",
                      {"status": "succeeded", "run_id": "run-1"}),
        }))
        assert deploy_gates._check_deployment_evidence(42) is True

    def test_no_run_is_false(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.latest_deployment_run":
                _resp("done_transition.latest_deployment_run",
                      {"status": "", "run_id": ""}),
        }))
        assert deploy_gates._check_deployment_evidence(42) is False


class TestLatestRunStatus:
    def test_returns_status_and_id(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.latest_deployment_run":
                _resp("done_transition.latest_deployment_run",
                      {"status": "executing", "run_id": "run-9"}),
        }))
        assert deploy_gates._get_latest_run_status(42) == ("executing", "run-9")

    def test_empty_when_no_run(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.latest_deployment_run":
                _resp("done_transition.latest_deployment_run",
                      {"status": "", "run_id": ""}),
        }))
        assert deploy_gates._get_latest_run_status(42) == ("", "")


class TestRunStageConsistency:
    def test_failed_suffix_blocks(self, monkeypatch, capsys):
        _install(monkeypatch, _router({
            "done_transition.run_stage":
                _resp("done_transition.run_stage",
                      {"current_stage": "production-failed"}),
        }))
        assert deploy_gates._check_run_stage_consistency("run-1") is True
        assert "current_stage='production-failed'" in capsys.readouterr().out

    def test_clean_stage_passes(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.run_stage":
                _resp("done_transition.run_stage", {"current_stage": "complete"}),
        }))
        assert deploy_gates._check_run_stage_consistency("run-1") is False

    def test_empty_run_id_short_circuits(self, monkeypatch):
        _install(monkeypatch, lambda **k: pytest.fail("must not relay for empty run"))
        assert deploy_gates._check_run_stage_consistency("") is False


class TestRunQaGates:
    def test_blocking_unsatisfied_blocks(self, monkeypatch, capsys):
        _install(monkeypatch, _router({
            "done_transition.run_blocking_qa":
                _resp("done_transition.run_blocking_qa",
                      {"blocking": ["smoke (failed)"]}),
        }))
        assert deploy_gates._check_run_qa_gates("run-1") is True
        out = capsys.readouterr().out
        assert "blocking QA checks are unsatisfied" in out
        assert "- smoke (failed)" in out

    def test_no_blocking_passes(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.run_blocking_qa":
                _resp("done_transition.run_blocking_qa", {"blocking": []}),
        }))
        assert deploy_gates._check_run_qa_gates("run-1") is False


class TestDeploymentFlowGuard:
    def test_unregistered_flow_blocks(self, monkeypatch, capsys):
        _install(monkeypatch, _router({
            "done_transition.registered_flow_ids":
                _resp("done_transition.registered_flow_ids",
                      {"flow_ids": ["yoke-internal"]}),
        }))
        result = deploy_gates._check_deployment_flow_guard(
            item_id=510, deploy_flow="garbage", skip_deploy=False,
            item_project="yoke", old_status="implemented",
            delivery_stage_id="ship-ready",
        )
        assert result == (7, "implemented")
        assert "is NOT a registered deployment flow" in capsys.readouterr().out

    def test_registered_succeeded_clean_proceeds(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.registered_flow_ids":
                _resp("done_transition.registered_flow_ids",
                      {"flow_ids": ["acme-prod"]}),
            "done_transition.latest_deployment_run":
                _resp("done_transition.latest_deployment_run",
                      {"status": "succeeded", "run_id": "run-1"}),
            "done_transition.run_stage":
                _resp("done_transition.run_stage", {"current_stage": "complete"}),
            "done_transition.run_blocking_qa":
                _resp("done_transition.run_blocking_qa", {"blocking": []}),
        }))
        result = deploy_gates._check_deployment_flow_guard(
            item_id=511, deploy_flow="acme-prod", skip_deploy=False,
            item_project="yoke", old_status="implemented",
            delivery_stage_id="ship-ready",
        )
        assert result is None

    def test_internal_flow_short_circuits_before_relay(self, monkeypatch):
        _install(monkeypatch, lambda **k: pytest.fail("internal flow must not relay"))
        result = deploy_gates._check_deployment_flow_guard(
            item_id=512, deploy_flow="yoke-internal", skip_deploy=False,
            item_project="yoke", old_status="implemented",
            delivery_stage_id="ship-ready",
        )
        assert result is None

    def test_failclosed_raises_on_unavailable_read(self, monkeypatch):
        _install(monkeypatch, _router({
            "done_transition.registered_flow_ids":
                _resp("done_transition.registered_flow_ids", success=False),
        }))
        with pytest.raises(RuntimeError):
            deploy_gates._check_deployment_flow_guard(
                item_id=513, deploy_flow="acme-prod", skip_deploy=False,
                item_project="yoke", old_status="implemented",
                delivery_stage_id="ship-ready",
            )
