"""Merge admission dispatches and records consumer proof for the exact pair."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.engines import merge_worktree_consumer_proof as proof

CANDIDATE = "a" * 40
CONSUMER = "b" * 40


@pytest.fixture
def gate(monkeypatch, tmp_path):
    ctx = SimpleNamespace(
        project="producer",
        worktree_path=str(tmp_path),
        public_ref="PROD-1",
        args=SimpleNamespace(branch="candidate", target="trunk"),
    )
    calls = []
    recorded = []
    run = {
        "run_id": "123",
        "state": "success",
        "head_sha": CONSUMER,
        "html_url": "https://example.test/run/123",
    }
    policy = {
        "producers": {
            "producer": {"contract_paths": ["api/**"], "workflow": "proof.yml"}
        }
    }

    def dispatch(*, function_id, payload, target, **kwargs):
        calls.append((function_id, payload, target, kwargs))
        results = {
            "projects.list": {
                "rows": [{"slug": "consumer", "default_branch": "trunk"}]
            },
            "projects.capability_settings.get": {"settings_json": json.dumps(policy)},
            "items.detail.get": {"item": {"status": "reviewing"}},
            "qa.requirement.list": {"rows": []},
            "qa.requirement.add": {"requirement_id": 42},
            "github.branch.head": {"head_sha": CONSUMER, "repo": "org/consumer"},
            "github_actions.dispatch_tag.ensure": {},
            "github_actions.workflow.dispatch": {"run_id": "123"},
            "github_actions.wait_run": run,
            "github_actions.failed_log": {"jobs": [{"name": "build consumer"}]},
            "qa.run.add": {"qa_run_id": 99},
            "qa.requirement.update": {},
        }
        if function_id == "qa.run.add":
            recorded.append(payload)
        return SimpleNamespace(success=True, result=results[function_id])

    git = Mock(
        side_effect=lambda checkout, *args: (
            "api/request.py" if args[0] == "diff" else CANDIDATE
        )
    )
    monkeypatch.setattr(proof, "_git", git)
    publisher = Mock()
    monkeypatch.setattr(proof.qa_case_ci_lane, "push_lane", publisher)
    waiter = Mock(return_value=(0, "success"))
    monkeypatch.setattr(proof.qa_case_ci_lane, "await_workflow", waiter)
    return SimpleNamespace(
        ctx=ctx,
        calls=calls,
        recorded=recorded,
        run=run,
        policy=policy,
        dispatch=dispatch,
        publisher=publisher,
        waiter=waiter,
        git=git,
    )


def test_dispatch_records_exact_pair_success(gate):
    assert proof.require_consumer_proof(gate.ctx, dispatch=gate.dispatch) == ""
    dispatched = next(
        row for row in gate.calls if row[0] == "github_actions.workflow.dispatch"
    )
    assert dispatched[1]["inputs"] == {"product_ref": CANDIDATE}
    assert dispatched[1]["ref"] == f"yoke-deploy/consumer-proof-{CONSUMER}"
    assert dispatched[3]["request_id"].startswith("consumer-proof:")
    gate.publisher.assert_called_once()
    assert gate.recorded[0]["head_sha"] == CANDIDATE
    assert gate.recorded[0]["verdict"] == "pass"
    raw = json.loads(gate.recorded[0]["raw_result"])
    assert raw["consumer_sha"] == CONSUMER
    assert raw["consumer_run"]["run_id"] == "123"


def test_non_contract_candidate_dispatches_nothing(gate):
    gate.policy["producers"]["producer"]["contract_paths"] = ["different/**"]
    assert proof.require_consumer_proof(gate.ctx, dispatch=gate.dispatch) == ""
    assert not any(row[0] == "github_actions.workflow.dispatch" for row in gate.calls)
    gate.publisher.assert_not_called()
    assert not gate.recorded


def test_failure_records_consumer_job_and_refuses(gate):
    gate.run.update(state="failed", conclusion="failure")
    refusal = proof.require_consumer_proof(gate.ctx, dispatch=gate.dispatch)
    assert "consumer_proof_failed" in refusal
    assert "build consumer" in refusal
    assert "https://example.test/run/123" in refusal
    assert "companion item" in refusal
    assert gate.recorded[0]["verdict"] == "fail"


def test_wrong_consumer_commit_never_passes(gate):
    gate.run["head_sha"] = "c" * 40
    assert "consumer_proof_failed" in proof.require_consumer_proof(
        gate.ctx, dispatch=gate.dispatch
    )
    assert gate.recorded[0]["verdict"] == "fail"


def test_retry_joins_same_dispatch_and_reuses_requirement(gate):
    original = gate.dispatch

    def dispatch(**kwargs):
        response = original(**kwargs)
        if kwargs["function_id"] == "qa.requirement.list":
            response.result = {
                "rows": [
                    {
                        "id": 42,
                        "suite_id": "consumer-proof:consumer",
                        "requirement_source": "flow_derived",
                    }
                ]
            }
        return response

    for _ in range(2):
        assert (
            proof.require_consumer_proof(gate.ctx, dispatch=dispatch, publish=False)
            == ""
        )
    identities = [
        row[3]["request_id"]
        for row in gate.calls
        if row[0] == "github_actions.workflow.dispatch"
    ]
    assert identities[0] == identities[1]
    assert not any(row[0] == "qa.requirement.add" for row in gate.calls)
    gate.publisher.assert_not_called()


def test_unavailable_read_refuses_before_dispatch(gate):
    def unavailable(**kwargs):
        return SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="forbidden", message="restore project access"),
        )

    refusal = proof.require_consumer_proof(gate.ctx, dispatch=unavailable)
    assert "consumer_proof_unavailable" in refusal
    assert "restore project access" in refusal
    gate.waiter.assert_not_called()


def test_dispatch_refusal_is_recorded_on_consumer_requirement(gate):
    original = gate.dispatch

    def dispatch(**kwargs):
        if kwargs["function_id"] == "github_actions.workflow.dispatch":
            return SimpleNamespace(
                success=False,
                error=SimpleNamespace(
                    code="forbidden", message="restore Actions access"
                ),
            )
        return original(**kwargs)

    refusal = proof.require_consumer_proof(gate.ctx, dispatch=dispatch)
    assert "restore Actions access" in refusal
    assert gate.recorded[0]["verdict"] == "fail"
    assert "restore Actions access" in gate.recorded[0]["raw_result"]
    gate.waiter.assert_not_called()


def test_undeclared_consumers_need_no_git_remote(gate):
    gate.policy["producers"] = {}
    assert proof.require_consumer_proof(gate.ctx, dispatch=gate.dispatch) == ""
    gate.git.assert_not_called()


def test_classic_merge_runs_consumer_gate_after_project_tests(monkeypatch, gate):
    from yoke_core.engines import merge_worktree_execute as execute

    order = []
    monkeypatch.setattr(
        execute, "_run_project_tests", lambda ctx: order.append("project")
    )
    monkeypatch.setattr(
        proof, "require_consumer_proof", lambda ctx: order.append("consumer") or ""
    )
    assert execute.run_tests(gate.ctx) is None
    assert order == ["project", "consumer"]


def test_queue_refusal_does_not_arm_the_landing(monkeypatch):
    from runtime.api.merge_queue_landing_test_helpers import wire_happy_path, land
    from yoke_core.domain import merge_queue_route

    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        proof,
        "require_consumer_proof",
        lambda *args, **kwargs: "consumer_proof_failed: build consumer",
    )
    arm = Mock()
    monkeypatch.setattr(merge_queue_route, "enter_merge_queue", arm)
    outcome = land()
    assert not outcome.ok
    assert "consumer_proof_failed" in outcome.error
    arm.assert_not_called()


def test_removing_contract_change_keeps_prior_evidence_nonblocking(gate):
    original = gate.dispatch
    gate.policy["producers"]["producer"]["contract_paths"] = ["different/**"]

    def dispatch(**kwargs):
        response = original(**kwargs)
        if kwargs["function_id"] == "qa.requirement.list":
            response.result = {
                "rows": [
                    {
                        "id": 42,
                        "suite_id": "consumer-proof:consumer",
                        "requirement_source": "flow_derived",
                        "blocking_mode": "blocking",
                    }
                ]
            }
        return response

    assert proof.require_consumer_proof(gate.ctx, dispatch=dispatch) == ""
    updates = [row for row in gate.calls if row[0] == "qa.requirement.update"]
    assert updates[0][1] == {"field": "blocking_mode", "value": "non_blocking"}
    gate.waiter.assert_not_called()
