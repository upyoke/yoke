"""Worker and release calls share exact durable dispatch identity."""

import json

import pytest

from runtime.api.tools import platform_consumer_dispatch as worker
from runtime.api.tools import require_platform_consumer_compatibility as gate
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import github_actions_rest
from yoke_core.domain.github_workflow_dispatch import dispatch_workflow_with_intent
from yoke_core.domain.handlers.github_actions_workflow_dispatch import WorkflowDispatchRequest
from yoke_core.domain.yoke_function_idempotency_scope import idempotency_payload_checksum

CANDIDATE = "a" * 40
CONSUMER = "b" * 40


def _request(argv, actor):
    inputs = {}
    for index, value in enumerate(argv):
        if value == "--input":
            key, text = argv[index + 1].split("=", 1)
            inputs[key] = text
    payload = dict(
        repo=argv[2], workflow=argv[3], ref=argv[argv.index("--ref") + 1],
        inputs=inputs, project=argv[argv.index("--project") + 1],
        correlation_input=argv[argv.index("--correlation-input") + 1],
    )
    return FunctionCallRequest(
        function="github_actions.workflow.dispatch",
        actor=ActorContext(actor_id=actor, session_id=f"session-{actor}"),
        target=TargetRef(kind="global"),
        request_id=argv[argv.index("--request-id") + 1],
        payload=payload, options={"authorized_project_id": 3},
    )


def test_worker_proof_is_joined_by_release_with_identical_checksum(tmp_path, monkeypatch):
    requests = []
    actor = "worker"
    posted = []

    def run(argv, *, timeout, stdin=None):
        if argv[1:3] == ["dispatch-tag", "ensure"]:
            return 0, json.dumps({"success": True, "result": {
                "repo": argv[3], "tag": argv[4], "sha": argv[5],
            }}), ""
        request = _request(argv, actor)
        requests.append(request)
        outcome = dispatch_workflow_with_intent(
            request, WorkflowDispatchRequest(**request.payload), "token",
        )
        assert outcome.primary_success
        return 0, outcome.result_payload["run_id"] + "\n", ""

    monkeypatch.setattr(worker, "_run", run)
    monkeypatch.setattr(gate, "_yoke", run)
    monkeypatch.setattr(github_actions_rest, "rest_post", lambda *a, **kw: (
        posted.append(kw["body"]) or {"workflow_run_id": "42"}
    ))
    monkeypatch.setattr(github_actions_rest, "rest_get", lambda *a, **kw: {
        "id": "42", "status": "completed", "conclusion": "success",
    })
    with init_test_db(tmp_path):
        assert worker.main(["--candidate-sha", CANDIDATE, "--consumer-sha", CONSUMER]) == 0
        actor = "release"
        assert gate.dispatch(CANDIDATE, CONSUMER) == ("42", "")
    assert len(posted) == 1
    assert requests[0].payload["inputs"] == {
        "product_ref": CANDIDATE, "consumer_sha": CONSUMER,
    }
    assert idempotency_payload_checksum(requests[0]) == idempotency_payload_checksum(requests[1])


@pytest.mark.parametrize("change", ["candidate", "consumer", "input"])
def test_changed_pair_or_payload_cannot_reuse_request_id(tmp_path, monkeypatch, change):
    argv = worker.build_dispatch(CANDIDATE, CONSUMER)
    original = _request(argv, "worker")
    changed = worker.build_dispatch(
        "c" * 40 if change == "candidate" else CANDIDATE,
        "d" * 40 if change == "consumer" else CONSUMER,
    )
    request = _request(changed, "release")
    if change != "input":
        assert request.request_id != original.request_id
    request.request_id = original.request_id
    if change == "input":
        request.payload["inputs"]["extra"] = "different"
    monkeypatch.setattr(github_actions_rest, "rest_post", lambda *a, **kw: {
        "workflow_run_id": "42",
    })
    with init_test_db(tmp_path):
        assert dispatch_workflow_with_intent(
            original, WorkflowDispatchRequest(**original.payload), "token",
        ).primary_success
        outcome = dispatch_workflow_with_intent(
            request, WorkflowDispatchRequest(**request.payload), "token",
        )
    assert outcome.error.code == "idempotency_key_collision"


def test_invalid_pair_is_refused_before_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(worker, "_run", lambda *a, **kw: pytest.fail("must not dispatch"))
    assert worker.main(["--candidate-sha", "short", "--consumer-sha", CONSUMER]) == 2
    assert "consumer_pair_invalid" in capsys.readouterr().err
