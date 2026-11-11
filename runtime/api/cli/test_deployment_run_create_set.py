"""Release-set creation sends every flow in one all-or-nothing create."""

import json

import pytest
from yoke_cli.commands.adapters import deployment_run_create as adapter
from yoke_cli.commands.adapters import deployment_run_create_set as release_set
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.function_serving_floors import declared_argument_floors

SHA = "a" * 40


@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("explicit", [False, True])
def test_every_flow_goes_in_one_create(monkeypatch, capsys, count, explicit):
    calls = _stub(monkeypatch)
    resolved = []
    monkeypatch.setattr(adapter, "resolve_commit_lineage",
                        lambda *args: resolved.append(args) or SHA)
    flows = [f"flow-{i}" for i in range(count)]
    args = ["project", *flows, "--idempotency-key", "release", "--json"]
    if explicit:
        args += ["--project-repo-path", "/checkout", "--source-ref", "main"]
    assert adapter.deployment_runs_create(args) == 0
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["flows"] == flows and "flow" not in payload
    assert payload["idempotency_key"] == "release"
    assert payload.get("release_lineage") == (SHA if explicit else None)
    assert len(resolved) == int(explicit)
    assert len(json.loads(capsys.readouterr().out)["result"]["runs"]) == count


def _stub(monkeypatch, *, refuse=False):
    calls = []
    monkeypatch.setattr(release_set, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(release_set, "build_actor", lambda **_: object())
    monkeypatch.setattr(release_set, "creation_connection_error", lambda *a, **k: None)
    monkeypatch.setattr(release_set, "pin_regression_error", lambda *_: None)

    def dispatch(**kwargs):
        calls.append(kwargs)
        flows = kwargs["payload"]["flows"]
        runs = [{"run_id": f"run-{i}", "flow": flow, "release_lineage": SHA}
                for i, flow in enumerate(flows)]
        return FunctionCallResponse(
            success=not refuse, function=kwargs["function_id"], version="v1",
            request_id="test", result={} if refuse else {"runs": runs},
            error=FunctionError(code="test_refusal", message="last flow refused") if refuse else None,
        )
    monkeypatch.setattr(release_set, "call_dispatcher", dispatch)
    return calls


def test_refusal_makes_no_compensating_calls(monkeypatch, capsys):
    calls = _stub(monkeypatch, refuse=True)
    assert adapter.deployment_runs_create([
        "project", "first", "second", "last", "--idempotency-key", "release",
    ]) != 0
    assert [c["function_id"] for c in calls] == ["deployment_runs.create"]
    assert "last flow refused" in capsys.readouterr().err


def test_flows_argument_names_its_serving_floor():
    assert set(declared_argument_floors("deployment_runs.create", {"flows": ["a", "b"]})) == {"flows"}
    assert declared_argument_floors("deployment_runs.create", {"flow": "a"}) == {}


@pytest.mark.parametrize("extra, message", [
    (["--environment", "prod"], "each flow owns its target"),
    (["--retry-of", "run-1"], "retry each flow's run on its own"),
])
def test_multiple_flows_refuse_single_run_options(monkeypatch, capsys, extra, message):
    calls = _stub(monkeypatch)
    assert adapter.deployment_runs_create([
        "project", "first", "last", *extra, "--idempotency-key", "key",
    ]) == 2
    assert calls == []
    assert message in capsys.readouterr().err
