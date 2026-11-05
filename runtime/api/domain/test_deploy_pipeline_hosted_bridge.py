"""Hosted dispatch endpoints follow the owning connection and fail closed."""

import pytest

from yoke_core.domain import deploy_pipeline_hosted_bridge as bridge


@pytest.mark.parametrize("owner", ["stage", "prod"])
@pytest.mark.parametrize("admin", [False, True])
def test_owner_connection_supplies_endpoint(monkeypatch, owner, admin):
    monkeypatch.setenv("YOKE_ENV", owner + ("-db-admin" if admin else ""))
    endpoint = f"https://{owner}.example/api/orgs/team"
    monkeypatch.setattr(
        bridge.machine_config,
        "load_config",
        lambda: {
            "connections": {
                owner: {"transport": "https", "api_url": endpoint},
                owner + "-db-admin": {"transport": "local-postgres"},
            },
        },
    )
    values, diagnostic = bridge.hosted_bridge_inputs(
        "platform-release-bridge.yml",
        {"control_plane_api_url": "https://wrong.example"},
    )
    assert diagnostic == ""
    assert values["control_plane_api_url"] == endpoint


@pytest.mark.parametrize(
    "connection",
    [
        {"transport": "local-postgres"},
        {"transport": "https", "api_url": ""},
        {"transport": "https", "api_url": "https://secret@example.com/api"},
        {"transport": "https", "api_url": "http://example.com/api"},
    ],
)
def test_missing_or_unsafe_owner_endpoint_refuses(monkeypatch, connection):
    monkeypatch.setenv("YOKE_ENV", "stage-db-admin")
    monkeypatch.setattr(
        bridge.machine_config,
        "load_config",
        lambda: {
            "connections": {"stage-db-admin": connection},
        },
    )
    values, diagnostic = bridge.hosted_bridge_inputs("platform-release-bridge.yml", {})
    assert values == {}
    assert diagnostic.startswith("release_control_endpoint_unavailable:")
    assert "secret" not in diagnostic


def test_other_workflows_need_no_hosted_connection(monkeypatch):
    def unexpected():
        pytest.fail("a customer workflow must not inspect hosted authority")

    monkeypatch.setattr(bridge.machine_config, "load_config", unexpected)
    assert bridge.hosted_bridge_inputs("deploy.yml", {"target": "local"}) == (
        {"target": "local"},
        "",
    )


@pytest.mark.parametrize("failure", [False, True])
def test_early_proof_uses_owner_authority_and_never_waits(monkeypatch, capsys, failure):
    import json
    import subprocess
    from yoke_core.domain import deploy_pipeline_reporting as reporting
    from runtime.api.tools import require_platform_consumer_compatibility as gate

    calls = []
    candidate, consumer = "a" * 40, "b" * 40

    def actions(*args, project, timeout):
        calls.append((args, project))
        if args[:2] == ("dispatch-tag", "ensure"):
            output = json.dumps({"success": True, "result": {
                "repo": args[2], "tag": args[3], "sha": args[4]}})
            return subprocess.CompletedProcess(args, 0, output, "")
        assert args[:3] == ("trigger", "upyoke/platform", "platform-release-pin-check.yml")
        return subprocess.CompletedProcess(args, int(failure), "42\n", "denied" if failure else "")

    monkeypatch.setattr(reporting, "_github_actions", actions)
    monkeypatch.setattr(gate, "await_verdict", lambda *a, **kw: pytest.fail("must not wait"))
    stages = [{"config": {"workflow": bridge.HOSTED_BRIDGE_WORKFLOW}}]
    bridge.start_hosted_consumer_proof(stages, candidate, {"consumer_sha": consumer})
    early_calls = list(calls)

    def run_yoke(argv, *, timeout):
        args = list(argv[1:])
        index = args.index("--project")
        project = args[index + 1]
        del args[index:index + 2]
        result = actions(*args, project=project, timeout=timeout)
        return result.returncode, result.stdout, result.stderr

    monkeypatch.setattr(gate, "_yoke", run_yoke)
    gate.dispatch(candidate, consumer)
    assert calls[2:] == early_calls  # Bridge joins the identical durable intent.
    assert all(project == "platform" for _, project in calls)
    output = capsys.readouterr().out
    assert ("consumer_proof_start_unavailable" if failure else "run 42") in output


@pytest.mark.parametrize("stages,inputs", [([], {}), ([{"config": {"workflow": "deploy.yml"}}], {}),
    ([{"config": {"workflow": bridge.HOSTED_BRIDGE_WORKFLOW}}], {})])
def test_unrelated_or_unbound_flow_never_dispatches(monkeypatch, stages, inputs):
    from yoke_core.domain import platform_consumer_dispatch as pairs
    monkeypatch.setattr(pairs, "dispatch_pair", lambda *a: pytest.fail("must not dispatch"))
    bridge.start_hosted_consumer_proof(stages, "a" * 40, inputs)
