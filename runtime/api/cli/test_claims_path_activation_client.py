"""Standalone activation shares machine-local head resolution with preflight."""

import json

import pytest

from yoke_cli.commands.adapters import claims_path_flow as cli
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import advance_path_claim_activation_retry as retry
from yoke_core.domain import project_checkout_locations as locations


REF = f"DEMO-{42}"


@pytest.fixture
def activation(monkeypatch):
    calls = []
    claims = [{"id": 7, "state": "planned", "integration_target": "trunk"}]
    result = {
        "outcomes": [
            {"claim_id": 7, "state_before": "planned", "state_after": "active"}
        ]
    }
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(cli, "sync_local_snapshot_for_write", lambda **kw: {})
    monkeypatch.setattr(
        locations, "checkout_for_project_id", lambda project: "/mapped/repo"
    )

    def resolve(*args, **kwargs):
        assert kwargs["repo_path"] == "/mapped/repo"
        assert kwargs["integration_target"] == "trunk"
        return retry.ResolveResult(
            commit_sha="a" * 40, error=None, diverged=False, attempts=1
        )

    monkeypatch.setattr(retry, "resolve_integration_head_with_retry", resolve)

    def dispatch(*, function_id, target, payload, actor):
        assert target.public_ref == REF
        assert actor.session_id == "activation-session"
        calls.append((function_id, payload))
        data = {
            "claims.path.list": {"claims": claims},
            "items.detail.get": {"item": {"project": {"id": 3}}},
            "claims.path.activation_run": result,
        }[function_id]
        return FunctionCallResponse(
            success=True, function=function_id, version="v1", result=data
        )

    monkeypatch.setattr(cli, "call_dispatcher", dispatch)
    return claims, result, calls


def run():
    return cli.claims_path_activation_run(
        ["--item", REF, "--session-id", "activation-session", "--json"]
    )


def test_https_shaped_activation_relays_machine_resolved_head(activation, capsys):
    assert run() == 0
    assert activation[2][-1] == (
        "claims.path.activation_run",
        {"resolved_heads": {7: "a" * 40}},
    )
    assert json.loads(capsys.readouterr().out)["success"] is True


def test_missing_checkout_refuses_before_activation(activation, monkeypatch, capsys):
    monkeypatch.setattr(locations, "checkout_for_project_id", lambda project: None)
    assert run() == 1
    output = capsys.readouterr()
    assert "path_claim_checkout_missing" in output.out + output.err
    assert "yoke project register" in output.out + output.err
    assert all(name != "claims.path.activation_run" for name, _ in activation[2])


@pytest.mark.parametrize(
    "failure",
    [
        {
            "outcomes": [
                {
                    "claim_id": 7,
                    "state_before": "planned",
                    "state_after": "planned",
                    "error": "head unavailable",
                }
            ]
        },
        {"blocked_errors": ["claim blocked"]},
        {"diverged_error": "integration diverged"},
        {
            "outcomes": [
                {"claim_id": 7, "state_before": "planned", "state_after": "planned"}
            ]
        },
    ],
)
def test_incomplete_activation_is_nonzero_and_preserves_evidence(
    activation, failure, capsys
):
    activation[1].clear()
    activation[1].update(failure)
    assert run() == 1
    output = capsys.readouterr()
    response = json.loads(output.out)
    assert response["success"] is False
    assert response["result"] == failure
    assert response["error"]["code"] == "path_claim_activation_incomplete"
    assert "retry" in response["error"]["recovery_hint"]


def test_no_claims_is_clean_success_without_checkout(activation, monkeypatch):
    activation[0].clear()
    activation[1].clear()
    monkeypatch.setattr(
        locations,
        "checkout_for_project_id",
        lambda project: pytest.fail("no checkout needed"),
    )
    assert run() == 0
    assert activation[2][-1] == ("claims.path.activation_run", {"resolved_heads": {}})
