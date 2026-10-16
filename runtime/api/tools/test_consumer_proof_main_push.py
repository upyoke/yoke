"""A main push starts the exact-pair proof that the release of that commit joins.

The fake control plane below keeps durable dispatch intents the way the
served ``github_actions.workflow.dispatch`` does: one request id names one
payload and one run, a repeated identical request rejoins that run, and the
same id with a different payload is a collision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from yoke_core.domain.yaml_helper import load_document

from runtime.api.tools import consumer_compatibility_advisory as advisory
from runtime.api.tools import require_platform_consumer_compatibility as gate

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "consumer-compatibility-advisory.yml"
CANDIDATE = "a" * 40
CONSUMER = "b" * 40


class ControlPlane:
    def __init__(self) -> None:
        self.head = CONSUMER
        self.intents: dict = {}
        self.posts = 0
        self.tags: dict = {}
        self.runs: dict = {}
        self.verdict = {"state": "success"}

    def __call__(self, argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        if argv[:3] == ["github", "branch", "head"]:
            result = {"head_sha": self.head}
            return 0, json.dumps({"success": True, "result": result}), ""
        if argv[1:3] == ["dispatch-tag", "ensure"]:
            self.tags[argv[4]] = argv[5]
            result = {"repo": argv[3], "tag": argv[4], "sha": argv[5]}
            return 0, json.dumps({"success": True, "result": result}), ""
        if argv[1] == "trigger":
            key = argv[argv.index("--request-id") + 1]
            payload = tuple(argv[: argv.index("--request-id")])
            if key in self.intents:
                recorded, run_id = self.intents[key]
                if recorded != payload:
                    return 1, "", "idempotency_key_collision"
                return 0, f"{run_id}\n", ""
            self.posts += 1
            run_id = str(9000 + self.posts)
            self.intents[key] = (payload, run_id)
            self.runs[run_id] = self.tags[argv[argv.index("--ref") + 1]]
            return 0, f"{run_id}\n", ""
        raise AssertionError(f"unexpected yoke call {argv}")

    def ref_of(self, key: str) -> str:
        payload = self.intents[key][0]
        return payload[payload.index("--ref") + 1]


@pytest.fixture
def plane(monkeypatch):
    plane = ControlPlane()
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(gate, "_yoke", plane)
    monkeypatch.setattr(gate, "bind_consumer_authority", lambda: "")

    def verdict(run_id, **_):
        # A tag-bound run's head is the tagged consumer commit.
        evidence = {"head_sha": plane.runs[run_id], "html_url": f"https://run/{run_id}"}
        return evidence | plane.verdict, ""

    monkeypatch.setattr(gate, "await_verdict", verdict)
    monkeypatch.setattr(
        advisory, "candidate_tree", lambda _: pytest.fail("exact pairs read no tree")
    )
    return plane


def test_release_joins_the_main_push_proof_of_the_same_pair(plane):
    assert advisory.check(CANDIDATE, timeout_sec=1, exact_pair=True)[0] == 0
    stage = gate.prove(CANDIDATE, CONSUMER, timeout_sec=1)
    prod = gate.prove(CANDIDATE, CONSUMER, timeout_sec=1)
    assert stage[0] == prod[0] == 0 and stage[2] == CONSUMER
    assert plane.posts == 1
    key = gate.pair_request_id(CANDIDATE, CONSUMER)
    assert list(plane.intents) == [key]
    assert plane.ref_of(key) == f"yoke-deploy/consumer-{CONSUMER}"
    assert plane.tags == {f"yoke-deploy/consumer-{CONSUMER}": CONSUMER}


def test_a_release_bound_after_platform_moved_proves_its_own_pair(plane):
    advisory.check(CANDIDATE, timeout_sec=1, exact_pair=True)
    moved = "e" * 40
    plane.head = moved
    code, _, proven = gate.prove(CANDIDATE, moved, timeout_sec=1)
    assert (code, proven, plane.posts) == (0, moved, 2)
    assert plane.ref_of(gate.pair_request_id(CANDIDATE, moved)).endswith(moved)


def test_a_newer_main_commit_never_reuses_or_replaces_the_older_proof(plane):
    advisory.check(CANDIDATE, timeout_sec=1, exact_pair=True)
    advisory.check("c" * 40, timeout_sec=1, exact_pair=True)
    assert plane.posts == 2
    assert gate.prove(CANDIDATE, CONSUMER, timeout_sec=1)[0] == 0
    assert plane.posts == 2


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_unfinished_or_failed_proof_is_reported_with_its_run(plane, conclusion):
    plane.verdict = {"state": "failed", "conclusion": conclusion}
    code, narrative = advisory.check(CANDIDATE, timeout_sec=1, exact_pair=True)
    assert code == gate.UNPROVEN
    assert conclusion in narrative and "https://run/9001" in narrative


def test_an_interrupted_wait_rejoins_the_same_run(plane):
    plane.verdict = {"state": "timeout"}
    assert advisory.check(CANDIDATE, timeout_sec=1, exact_pair=True)[0] == (
        gate.UNAVAILABLE
    )
    plane.verdict = {"state": "success"}
    assert gate.prove(CANDIDATE, CONSUMER, timeout_sec=1)[0] == 0
    assert plane.posts == 1


def test_missing_credential_reports_not_checked_for_an_exact_pair(monkeypatch, capsys):
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)
    assert advisory.main(["--candidate-sha", CANDIDATE, "--exact-pair"]) == 0
    assert "consumer_credential_missing" in capsys.readouterr().out


def test_only_pull_requests_get_the_superseding_advisory() -> None:
    workflow = load_document(WORKFLOW)
    concurrency = workflow["concurrency"]
    assert "github.sha" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
    job = workflow["jobs"]["advisory"]
    run = next(
        step["run"] for step in job["steps"] if advisory.__name__ in step.get("run", "")
    )
    assert "${{ github.event_name != 'pull_request' && '--exact-pair' || '' }}" in run
    budget = int(run.split("--timeout ")[1].split()[0])
    # The step reports its own timeout before the job timeout cancels it.
    assert budget + gate._COMMAND_TIMEOUT_SECONDS <= job["timeout-minutes"] * 60


def test_a_manual_exact_pair_run_is_dispatchable_with_recovery() -> None:
    workflow = load_document(WORKFLOW)
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"yoke_dispatch_id"}
    assert not inputs["yoke_dispatch_id"]["required"]
    assert "[yoke-dispatch:{0}]" in workflow["run-name"]
