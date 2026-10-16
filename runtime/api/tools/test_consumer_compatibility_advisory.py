"""Every candidate gets truthful, independent, content-keyed advisory evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from yoke_core.domain.yaml_helper import load_document
from runtime.api.tools import consumer_compatibility_advisory as advisory
from runtime.api.tools import require_platform_consumer_compatibility as gate

REPO_ROOT = Path(__file__).resolve().parents[3]
YOKE_CI = REPO_ROOT / ".github/workflows/yoke-ci.yml"
MERGE_QUEUE = REPO_ROOT / ".yoke/merge-queue.json"
ADVISORY_MODULE = "runtime.api.tools.consumer_compatibility_advisory"
CANDIDATE = "a" * 40
TREE = "d" * 40
CONSUMER = "b" * 40


@pytest.fixture(autouse=True)
def isolate_step_summary(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


@pytest.fixture
def proof(monkeypatch):
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")
    monkeypatch.setattr(gate, "bind_consumer_authority", lambda: "")
    monkeypatch.setattr(advisory, "candidate_tree", lambda _: TREE)
    reads, dispatches = [], []
    receipts = {}
    head = {"sha": CONSUMER}

    def read(argv):
        reads.append(argv)
        if argv[:3] == ["github", "branch", "head"]:
            return {"head_sha": head["sha"]}
        return receipts.get(argv[3], {"found": False})

    def dispatch(candidate, consumer, *, exact_pair, request_id):
        dispatches.append((candidate, consumer, request_id))
        assert exact_pair is False
        if request_id in receipts:
            prior = receipts[request_id]
            if prior["inputs"]["product_ref"] != candidate:
                return "", "request_id is bound to a different payload"
            prior["run_id"] = prior.get("run_id") or "recovered"
            return prior["run_id"], ""
        run = str(len(receipts) + 1)
        receipts[request_id] = {
            "found": True,
            "inputs": {"product_ref": candidate},
            "run_id": run,
        }
        return run, ""

    monkeypatch.setattr(advisory, "_read", read)
    monkeypatch.setattr(gate, "dispatch", dispatch)
    monkeypatch.setattr(
        gate,
        "await_verdict",
        lambda run_id, **_: (
            {
                "state": "success",
                "head_sha": head["sha"],
                "html_url": f"https://example.invalid/run/{run_id}",
            },
            "",
        ),
    )
    return reads, dispatches, receipts, head


def test_identical_trees_under_different_commits_share_one_platform_run(proof):
    reads, dispatches, _, _ = proof
    assert advisory.check(CANDIDATE, timeout_sec=1)[0] == 0
    assert advisory.check("c" * 40, timeout_sec=1)[0] == 0
    assert len(dispatches) == 1
    assert TREE in dispatches[0][2] and CONSUMER in dispatches[0][2]
    assert sum(argv[:3] == ["github", "branch", "head"] for argv in reads) == 2


def test_consumer_movement_and_product_tree_changes_get_new_runs(proof, monkeypatch):
    _, dispatches, _, head = proof
    advisory.check(CANDIDATE, timeout_sec=1)
    head["sha"] = "e" * 40
    advisory.check(CANDIDATE, timeout_sec=1)
    monkeypatch.setattr(advisory, "candidate_tree", lambda _: "f" * 40)
    advisory.check(CANDIDATE, timeout_sec=1)
    assert len({entry[2] for entry in dispatches}) == 3


def test_failed_proof_is_reused_without_redispatch(proof, monkeypatch):
    _, dispatches, _, _ = proof
    monkeypatch.setattr(
        gate,
        "await_verdict",
        lambda *_, **__: (
            {
                "state": "failed",
                "conclusion": "failure",
                "head_sha": CONSUMER,
            },
            "",
        ),
    )
    assert advisory.check(CANDIDATE, timeout_sec=1)[0] == gate.UNPROVEN
    assert advisory.check(CANDIDATE, timeout_sec=1)[0] == gate.UNPROVEN
    assert len(dispatches) == 1


def test_racing_identical_trees_recover_the_winners_original_input(proof, monkeypatch):
    _, dispatches, receipts, _ = proof
    original_dispatch = gate.dispatch

    def race(candidate, consumer, **kwargs):
        receipts[kwargs["request_id"]] = {
            "found": True,
            "inputs": {"product_ref": "c" * 40},
            "run_id": "winner",
        }
        return original_dispatch(candidate, consumer, **kwargs)

    monkeypatch.setattr(gate, "dispatch", race)
    assert advisory.check(CANDIDATE, timeout_sec=1)[0] == 0
    assert len(dispatches) == 1


def test_missing_run_recovers_pending_receipt_with_original_payload(proof):
    _, dispatches, receipts, _ = proof
    key = f"consumer-advisory:{TREE}:{CONSUMER}:{gate.CONSUMER_CHECK_WORKFLOW}"
    receipts[key] = {"found": True, "inputs": {"product_ref": "c" * 40}, "run_id": ""}
    assert advisory.check(CANDIDATE, timeout_sec=1)[0] == 0
    assert dispatches[0][0] == "c" * 40


def test_denied_receipt_read_names_the_run_read_grant(proof, monkeypatch):
    _, dispatches, _, _ = proof

    def denied(argv):
        if argv[:3] == ["github", "branch", "head"]:
            return {"head_sha": CONSUMER}
        raise RuntimeError("permission_denied: actor 170 lacks 'project.admin'")

    monkeypatch.setattr(advisory, "_read", denied)
    with pytest.raises(RuntimeError, match="dispatch_receipt_unauthorized") as err:
        advisory.check(CANDIDATE, timeout_sec=1)
    assert "github_actions.run.read" in str(err.value)
    assert "never grant project.admin" in str(err.value)
    assert dispatches == []


def test_wrong_original_tree_refuses_before_dispatch(proof, monkeypatch):
    _, dispatches, receipts, _ = proof
    key = f"consumer-advisory:{TREE}:{CONSUMER}:{gate.CONSUMER_CHECK_WORKFLOW}"
    receipts[key] = {"found": True, "inputs": {"product_ref": "c" * 40}, "run_id": "1"}
    monkeypatch.setattr(
        advisory, "candidate_tree", lambda sha: TREE if sha == CANDIDATE else "f" * 40
    )
    with pytest.raises(RuntimeError, match="advisory_proof_identity_mismatch"):
        advisory.check(CANDIDATE, timeout_sec=1)
    assert not dispatches


def test_moved_trunk_cannot_be_reported_as_the_keyed_proof(proof, monkeypatch):
    monkeypatch.setattr(
        gate,
        "await_verdict",
        lambda *_, **__: (
            {
                "state": "success",
                "head_sha": "e" * 40,
            },
            "",
        ),
    )
    code, narrative = advisory.check(CANDIDATE, timeout_sec=1)
    assert code == gate.UNPROVEN
    assert "stale pair" in narrative


def test_docs_only_candidate_is_checked_without_a_path_filter(proof, capsys):
    assert advisory.main(["--candidate-sha", CANDIDATE]) == 0
    assert len(proof[1]) == 1
    assert "hosted consumer builds" in capsys.readouterr().out


def test_fork_missing_credential_reports_not_checked(monkeypatch, capsys):
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)
    assert advisory.main(["--candidate-sha", CANDIDATE]) == 0
    assert "consumer_credential_missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error", ["function_version_skew: next-release", "relay unavailable"]
)
def test_unavailable_evidence_names_recovery(proof, monkeypatch, capsys, error):
    def refuse(_):
        raise RuntimeError(error)

    monkeypatch.setattr(advisory, "_read", refuse)
    assert advisory.main(["--candidate-sha", CANDIDATE]) == gate.UNAVAILABLE
    printed = capsys.readouterr().out
    assert "NOT CHECKED" in printed and error in printed
    assert "control-plane operator" in printed


def test_real_git_commits_with_identical_contents_have_one_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "file").write_text("same content")
    git("add", "file")
    git("commit", "-qm", "first")
    first = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "second")
    second = git("rev-parse", "HEAD")
    assert first != second
    assert advisory.candidate_tree(first) == advisory.candidate_tree(second)


CONSUMER_ADVISORY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "consumer-compatibility-advisory.yml"
)


def test_advisory_timeout_cannot_cancel_the_required_qa_workflow() -> None:
    # QA adopts the WHOLE yoke-ci run conclusion. Job-level continue-on-error
    # did not isolate a reusable advisory's timeout from that conclusion.
    required = load_document(YOKE_CI)
    evidence = load_document(CONSUMER_ADVISORY_WORKFLOW)
    assert evidence["name"] != required["name"]
    assert set(evidence[True]) == {
        "pull_request",
        "push",
        "workflow_dispatch",
    }
    assert evidence[True]["pull_request"]["branches"] == ["main"]
    assert evidence[True]["push"]["branches"] == ["main"]
    assert evidence["concurrency"]["group"] == (
        "${{ github.workflow }}-${{ github.ref }}"
    )
    assert set(required["jobs"]) == {
        "repo_contracts",
        "reuse_coverage",
        "test_shard",
        "browser_runtime",
        "container",
    }
    for job in required["jobs"].values():
        assert "consumer" not in str(job)
        assert not job.get("continue-on-error")
    assert required["permissions"] == {"contents": "read"}


def test_advisory_records_its_own_failures_with_one_scoped_credential() -> None:
    workflow = load_document(CONSUMER_ADVISORY_WORKFLOW)
    job = workflow["jobs"]["advisory"]
    token = gate.CONSUMER_TOKEN_ENV

    assert workflow["name"] == "consumer-compatibility-advisory"
    assert workflow["permissions"] == {"contents": "read"}
    assert job["if"] == "github.repository == 'upyoke/yoke'"
    assert not job.get("needs")
    assert not job.get("continue-on-error")
    assert token not in (job.get("env") or {})
    carrying = [step for step in job["steps"] if token in (step.get("env") or {})]
    assert len(carrying) == 1
    step = carrying[0]
    assert ADVISORY_MODULE in str(step["run"])
    assert step["env"][token] == "${{ secrets." + token + " }}"
    assert not step.get("continue-on-error")


def test_no_other_workflow_carries_the_scoped_consumer_credential() -> None:
    # It belongs to the release bridge and the one advisory step. Anywhere
    # else would be a second place to reason about who can reach the consumer.
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    carrying = {
        path.name
        for path in workflows
        if gate.CONSUMER_TOKEN_ENV in path.read_text(encoding="utf-8")
    }

    assert carrying == {
        "consumer-compatibility-advisory.yml",
        "platform-release-bridge.yml",
    }


def test_the_advisory_job_carries_no_required_status_check() -> None:
    # Independence buys nothing if the queue starts waiting on it anyway.
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    contexts = {
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    }

    assert "consumer-advisory" not in contexts
    assert not any("consumer-compatibility-advisory" in c for c in contexts)
