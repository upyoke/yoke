"""The release proof can replace one stale failure under a stable request key."""

import json
import subprocess

import pytest

from runtime.api.tools import require_platform_consumer_compatibility as gate
from yoke_core.domain.ci_run_redispatch import redispatch_request_id
from yoke_core.domain.platform_consumer_dispatch import pair_request_id
from yoke_core.tools import promote_main_artifacts

CANDIDATE = "a" * 40
CONSUMER = "b" * 40
EARLY = "2026-11-22T14:00:00.000000Z"
RECOVERY = "2026-11-22T14:01:00Z"
LATE = "2026-11-22T14:02:00.000000Z"


def verdict(run_id, updated_at, conclusion="failure"):
    return {
        "state": "failed" if conclusion == "failure" else conclusion,
        "status": "completed",
        "conclusion": conclusion,
        "updated_at": updated_at,
        "head_sha": CONSUMER,
        "html_url": f"https://github.com/upyoke/platform/actions/runs/{run_id}",
    }


@pytest.fixture
def proof(monkeypatch):
    def setup(first, *, replacement=None, lookup_error=False):
        dispatches, waits, lookups = [], [], []

        def run_yoke(args, *, timeout):
            if args[1:3] == ["dispatch-tag", "ensure"]:
                repo, tag, sha = args[3:6]
                receipt = {"success": True, "result": {"repo": repo, "tag": tag, "sha": sha}}
                return 0, json.dumps(receipt), ""
            if args[1] == "trigger":
                dispatches.append(args[args.index("--request-id") + 1])
                assert f"consumer_sha={CONSUMER}" in args
                assert f"product_ref={CANDIDATE}" in args
                return 0, str(len(dispatches)), ""
            assert args[:2] == ["github-actions", "wait-run"]
            waits.append(args[3])
            result = {"1": first, "2": replacement}[args[3]]
            return (0 if result["state"] == "success" else 1), json.dumps({"result": result}), ""

        def lookup(command):
            lookups.append(command)
            if lookup_error:
                raise subprocess.CalledProcessError(1, command, stderr="gh requires a token")
            return json.dumps({
                "workflow_runs": [{
                    "id": 99, "head_sha": CANDIDATE, "head_branch": "main", "event": "push",
                    "head_repository": {"full_name": "upyoke/yoke"}, "status": "completed",
                    "conclusion": "success", "updated_at": RECOVERY,
                }],
            })

        monkeypatch.setattr(gate, "_yoke", run_yoke)
        monkeypatch.setattr(promote_main_artifacts, "run", lookup)
        return dispatches, waits, lookups

    return setup


@pytest.mark.parametrize("replacement_conclusion", ["success", "failure"])
def test_stale_consumer_dispatches_and_awaits_once(proof, replacement_conclusion):
    replacement = verdict(2, EARLY, replacement_conclusion)
    dispatches, waits, lookups = proof(verdict(1, EARLY), replacement=replacement)
    result = gate.prove_pair(CANDIDATE, CONSUMER, timeout_sec=7)
    pair = pair_request_id(CANDIDATE, CONSUMER)
    assert dispatches == [pair, redispatch_request_id(pair, "1")]
    assert waits == ["1", "2"]
    assert len(lookups) == 1
    assert "/workflows/yoke-build-artifacts.yml/" in lookups[0][-1]
    assert result == gate.classify(
        replacement, candidate_sha=CANDIDATE, consumer_sha=CONSUMER, run_id="2",
    )


@pytest.mark.parametrize(("completed_at", "lookup_error"), [(LATE, False), (EARLY, True)])
def test_current_failure_and_unavailable_factory_keep_the_same_refusal(
    proof, completed_at, lookup_error
):
    failed = verdict(1, completed_at)
    dispatches, waits, lookups = proof(failed, lookup_error=lookup_error)
    result = gate.prove_pair(CANDIDATE, CONSUMER, timeout_sec=7)
    assert dispatches == [pair_request_id(CANDIDATE, CONSUMER)]
    assert waits == ["1"]
    assert len(lookups) == 1
    assert result == gate.classify(
        failed, candidate_sha=CANDIDATE, consumer_sha=CONSUMER, run_id="1",
    )
