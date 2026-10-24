"""Exact-main factory admission, single rerun ownership, and early refusals."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.domain import deploy_pipeline_factory_gate as client
from yoke_core.domain import github_actions_factory_gate as factory
from yoke_core.domain.handlers.github_actions_check_ci import CheckCiRequest

SHA = "a" * 40
NEWEST = "b" * 40
REPO = "owner/repo"
WORKFLOW = "factory.yml"


def run(**changes):
    return {
        "id": 42, "head_sha": SHA, "head_branch": "main", "event": "push",
        "head_repository": {"full_name": REPO},
        "path": f".github/workflows/{WORKFLOW}", "run_attempt": 1,
        "status": "completed", "conclusion": "success", "run_number": 1,
        **changes,
    }


def invoke():
    return factory.check_main_factory(
        CheckCiRequest(
            repo=REPO, workflow=WORKFLOW, project="example",
            branch="main", head_sha=SHA, main_factory=True,
        ),
        token="token",
        request=SimpleNamespace(
            actor=SimpleNamespace(actor_id="2"),
            options={"authorized_project_id": 7},
        ),
    )


@pytest.fixture
def relay(monkeypatch):
    reads, posts = Mock(), Mock()
    monkeypatch.setattr(factory, "rest_get", reads)
    monkeypatch.setattr(factory, "rest_post", posts)
    return reads, posts


def test_main_push_success_is_required_even_when_queue_has_identical_sha(relay):
    reads, posts = relay
    reads.side_effect = [
        {"workflow_runs": [run(event="merge_group"), run(head_branch="topic")]},
        {"workflow_runs": [run(head_sha=NEWEST)]},
    ]
    result = invoke().result_payload
    assert result["state"] == "no_runs"
    assert result["newest_successful_main_sha"] == NEWEST
    assert reads.call_args_list[0].kwargs["query"] == {
        "head_sha": SHA, "branch": "main", "event": "push", "per_page": "100",
    }
    posts.assert_not_called()


@pytest.mark.parametrize("status", ["queued", "in_progress", "pending"])
def test_gate_waits_for_whole_factory(relay, status):
    reads, posts = relay
    reads.return_value = {"workflow_runs": [run(status=status, conclusion=None)]}
    assert invoke().result_payload["state"] == "running"
    posts.assert_not_called()


def test_successful_exact_main_factory_passes(relay):
    reads, posts = relay
    reads.return_value = {"workflow_runs": [run()]}
    assert invoke().result_payload["state"] == "passed"
    posts.assert_not_called()


def test_failed_factory_refuses_and_names_newest_success(relay):
    reads, posts = relay
    reads.side_effect = [
        {"workflow_runs": [run(conclusion="failure")]},
        {"workflow_runs": [run(head_sha=NEWEST, run_number=20)]},
    ]
    result = invoke().result_payload
    assert result["state"] == "failed"
    assert result["newest_successful_main_sha"] == NEWEST
    posts.assert_not_called()


def test_cancelled_first_attempt_reruns_once_across_release_drivers(relay, monkeypatch):
    reads, posts = relay
    cancelled = run(conclusion="cancelled")
    reads.side_effect = [
        {"workflow_runs": [cancelled]}, cancelled,
        {"workflow_runs": [cancelled]}, cancelled,
    ]
    claim = Mock(side_effect=[True, False])
    monkeypatch.setattr(factory, "claim_attempt", claim)
    monkeypatch.setattr(factory, "latest_intent", lambda key: SimpleNamespace())
    completed = Mock()
    monkeypatch.setattr(factory, "complete_intent", completed)
    assert invoke().result_payload["state"] == "running"
    assert invoke().result_payload["state"] == "running"
    posts.assert_called_once_with(
        f"/repos/{REPO}/actions/runs/42/rerun",
        body={}, token="token", max_attempts=1,
    )
    assert claim.call_args_list[0] == claim.call_args_list[1]
    completed.assert_called_once()


def test_second_cancelled_attempt_refuses_without_another_rerun(relay):
    reads, posts = relay
    reads.side_effect = [
        {"workflow_runs": [run(conclusion="cancelled", run_attempt=2)]},
        {"workflow_runs": [run(head_sha=NEWEST)]},
    ]
    result = invoke().result_payload
    assert result["state"] == "failed"
    assert result["newest_successful_main_sha"] == NEWEST
    posts.assert_not_called()


def test_rerun_transport_failure_is_named_and_not_retried(relay, monkeypatch):
    from yoke_core.domain.gh_rest_transport import RestTransportError

    reads, posts = relay
    cancelled = run(conclusion="cancelled")
    reads.side_effect = [{"workflow_runs": [cancelled]}, cancelled]
    monkeypatch.setattr(factory, "claim_attempt", lambda **kwargs: True)
    posts.side_effect = RestTransportError("response lost")
    outcome = invoke()
    assert outcome.error.code == "main_factory_unavailable"
    assert "never retried" in outcome.error.message
    assert posts.call_count == 1


def test_rerun_refuses_changed_identity(relay):
    reads, posts = relay
    reads.side_effect = [
        {"workflow_runs": [run(conclusion="cancelled")]},
        run(head_sha=NEWEST),
    ]
    assert invoke().error.code == "main_factory_unavailable"
    posts.assert_not_called()


def test_malformed_factory_response_fails_closed(relay):
    reads, posts = relay
    reads.return_value = {}
    assert invoke().error.code == "main_factory_unavailable"
    posts.assert_not_called()


def adapter_result(**result):
    return subprocess.CompletedProcess(
        [], 0, json.dumps({"success": True, "result": result}), "",
    )


def test_client_uses_existing_ci_wait_and_factory_proof():
    relay = Mock(return_value=adapter_result(
        main_factory_checked=True, state="passed",
    ))
    assert client.check_main_factory(
        REPO, "example", SHA, 60, github_actions=relay
    )[0]
    args = relay.call_args.args
    assert "--wait" in args and "--main-factory" in args
    assert args[args.index("--head-sha") + 1] == SHA


def test_client_refuses_old_serving_response():
    relay = Mock(return_value=adapter_result(state="passed"))
    passed, message = client.check_main_factory(
        REPO, "example", SHA, 60, github_actions=relay,
    )
    assert not passed
    assert "main_factory_gate_version_skew" in message
    assert "source-dev" in message


def test_client_refusal_names_newest_successful_main_commit():
    relay = Mock(return_value=adapter_result(
        main_factory_checked=True, state="failed", run_id=42,
        conclusion="failure", newest_successful_main_sha=NEWEST,
    ))
    passed, message = client.check_main_factory(
        REPO, "example", SHA, 60, github_actions=relay,
    )
    assert not passed
    assert NEWEST in message
    assert "before dispatch" in message


def test_existing_ci_gate_checks_factory_only_after_ci_passes(monkeypatch):
    from yoke_core.domain import deploy_pipeline_gates as gates

    monkeypatch.setattr(gates, "project_ci_workflow_file", lambda project: "ci.yml")
    relay = Mock(side_effect=[
        adapter_result(state="passed"),
        adapter_result(main_factory_checked=True, state="failed", newest_successful_main_sha=NEWEST),
    ])
    monkeypatch.setattr(gates, "_github_actions", relay)
    passed, message = gates._check_ci_gate(
        REPO, "example", 60, branch="main", head_sha=SHA, main_factory=True,
    )
    assert not passed and NEWEST in message
    assert relay.call_count == 2


def test_ci_handler_routes_factory_mode_through_authorized_relay(monkeypatch):
    from runtime.api.domain.handlers.check_ci_test_support import (
        _make_request, stub_resolver,
    )
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    )
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    handler = stub_resolver(monkeypatch)
    resolver = Mock(return_value=ProjectGithubAuth(
        project="example", repo=REPO, token="token",
    ))
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth", resolver,
    )
    check = Mock(return_value=SimpleNamespace(primary_success=True))
    monkeypatch.setattr(factory, "check_main_factory", check)
    request = _make_request({
        "repo": REPO, "workflow": WORKFLOW, "project": "example",
        "branch": "main", "head_sha": SHA, "main_factory": True,
    })
    assert handler.handle_check_ci(request).primary_success
    assert resolver.call_args.kwargs["required_permissions"] == GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS
    assert check.call_args.kwargs["request"] is request


def test_ci_adapter_sends_explicit_factory_mode(monkeypatch):
    from yoke_cli.commands.adapters import github_actions

    monkeypatch.setattr(github_actions, "_default_timeout_seconds", lambda: 60)
    dispatch = Mock(return_value=0)
    monkeypatch.setattr(github_actions, "dispatch_and_emit", dispatch)
    assert github_actions.github_actions_check_ci([
        REPO, WORKFLOW, "--main-factory", "--head-sha", SHA,
        "--project", "example", "--json",
    ]) == 0
    assert dispatch.call_args.kwargs["payload"]["main_factory"] is True


def test_hosted_bridge_enables_factory_gate_before_dispatch(monkeypatch):
    from yoke_core.domain import deploy_pipeline_github_workflow as workflow
    from yoke_core.domain.hosted_promotion_receipt import HOSTED_BRIDGE_WORKFLOW

    monkeypatch.setattr(workflow, "_resolve_release_lineage_sha", lambda *a: (SHA, ""))
    observed = []

    def readiness(ci_gate, preparation):
        observed.append(ci_gate.keywords)
        return 1, "factory refused before dispatch"

    monkeypatch.setattr(workflow.readiness, "await_dispatch_readiness", readiness)
    result = workflow._dispatch_github_actions_workflow(
        {"workflow": HOSTED_BRIDGE_WORKFLOW}, name="hosted-release", run_id="run",
        member_items=[], github_repo=REPO, project="example", project_repo_path="/repo",
        timeout_min=1, fresh=False, gate_branch="main", release_lineage=SHA, sd="/tmp",
    )
    assert result == (1, "factory refused before dispatch")
    assert observed[0]["main_factory"] is True
