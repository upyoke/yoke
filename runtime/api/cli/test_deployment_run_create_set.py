"""Release-set creation binds one commit and compensates refused creates."""

import pytest
from yoke_cli.commands.adapters import deployment_run_create as adapter
from yoke_cli.commands.adapters import deployment_run_create_set as release_set
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

SHA = "a" * 40


@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("explicit", [False, True])
def test_every_flow_uses_one_source(monkeypatch, capsys, count, explicit):
    calls = _stub(monkeypatch)
    resolved = []
    monkeypatch.setattr(adapter, "resolve_commit_lineage",
                        lambda *args: resolved.append(args) or SHA)
    flows = [f"flow-{i}" for i in range(count)]
    args = ["project", *flows, "--idempotency-key", "release", "--json"]
    if explicit:
        args += ["--project-repo-path", "/checkout", "--source-ref", "main"]
    assert adapter.deployment_runs_create(args) == 0
    creates = [c["payload"] for c in calls]
    assert [c["flow"] for c in creates] == flows
    assert [c["idempotency_key"] for c in creates] == [f"release:{f}" for f in flows]
    assert all(c["release_lineage"] == SHA for c in creates[int(not explicit):])
    assert len(resolved) == int(explicit)
    import json
    assert len(json.loads(capsys.readouterr().out)["result"]["runs"]) == count


def _stub(monkeypatch, *, refuse_last=False):
    calls = []
    monkeypatch.setattr(release_set, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(release_set, "build_actor", lambda **_: object())
    monkeypatch.setattr(release_set, "creation_connection_error", lambda *a, **k: None)
    monkeypatch.setattr(release_set, "pin_regression_error", lambda *_: None)

    def dispatch(**kwargs):
        calls.append(kwargs)
        payload = kwargs["payload"]
        refusal = refuse_last and payload.get("flow") == "last"
        return FunctionCallResponse(
            success=not refusal, function=kwargs["function_id"], version="v1",
            request_id="test", result={"run_id": f"run-{len(calls)}", "release_lineage": SHA},
            error=FunctionError(code="test_refusal", message="last flow refused") if refusal else None,
        )
    monkeypatch.setattr(release_set, "call_dispatcher", dispatch)
    return calls


def test_last_refusal_cancels_earlier_runs(monkeypatch, capsys):
    calls = _stub(monkeypatch, refuse_last=True)
    assert adapter.deployment_runs_create([
        "project", "first", "second", "last", "--idempotency-key", "release",
    ]) != 0
    assert [c["function_id"] for c in calls] == ["deployment_runs.create"] * 3 + ["deployment_runs.terminalize"] * 2
    assert [c["target"].workflow_run_id for c in calls[3:]] == ["run-2", "run-1"]
    assert all(c["payload"]["disposition"] == "cancelled" for c in calls[3:])
    assert "last flow refused" in capsys.readouterr().err


def test_multiple_flows_refuse_environment_override(monkeypatch, capsys):
    calls = _stub(monkeypatch)
    assert adapter.deployment_runs_create([
        "project", "first", "last", "--environment", "prod", "--idempotency-key", "key",
    ]) == 2
    assert calls == []
    assert "each flow owns its target" in capsys.readouterr().err
