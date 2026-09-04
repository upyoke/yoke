"""Where the consumer-compatibility gate is wired into delivery.

The gate's logic is only half the guarantee. It has to be *required* at the
landing boundary — a red advisory check does not stop a merge-queue entry —
and it has to run again at the release boundary before the first
irreversible act, because both trunks move between a landing and a release.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.yaml_helper import load_document

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE_WORKFLOW = WORKFLOWS / "yoke-consumer-compatibility.yml"
RELEASE_BRIDGE = WORKFLOWS / "platform-release-bridge.yml"
MERGE_QUEUE = REPO_ROOT / ".yoke" / "merge-queue.json"
GATE_MODULE = "runtime.api.tools.require_platform_consumer_compatibility"
GATE_CONTEXT = "consumer-compatibility"


def _bridge_steps() -> list[dict]:
    workflow = load_document(RELEASE_BRIDGE)
    return workflow["jobs"]["dispatch-platform-release"]["steps"]


def _step_index(steps: list[dict], predicate) -> int:
    return next(index for index, step in enumerate(steps) if predicate(step))


def test_the_gate_declares_itself_a_required_landing_check() -> None:
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    contexts = {
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    }

    assert GATE_CONTEXT in contexts


def test_the_gate_workflow_reports_on_both_landing_events() -> None:
    workflow = load_document(GATE_WORKFLOW)
    # `on` is YAML 1.1 truthy; the loader may hand it back as the bool key.
    triggers = workflow.get("on", workflow.get(True))

    assert set(triggers) == {"pull_request", "merge_group"}
    job = workflow["jobs"]["consumer_compatibility"]
    assert job["name"] == GATE_CONTEXT
    # An event filter on the job would leave the required context absent
    # rather than concluded, which strands a queue entry rather than
    # failing it.
    assert "if" not in job
    assert any(GATE_MODULE in str(step.get("run", "")) for step in job["steps"])


def test_the_scoped_credential_reaches_only_the_step_that_spends_it() -> None:
    # Everything else in this job runs the candidate's own tree.
    workflow = load_document(GATE_WORKFLOW)
    job = workflow["jobs"]["consumer_compatibility"]
    token = "YOKE_PLATFORM_RELEASE_API_TOKEN"

    assert token not in (job.get("env") or {})
    carrying = [step for step in job["steps"] if token in (step.get("env") or {})]
    assert len(carrying) == 1
    assert GATE_MODULE in str(carrying[0]["run"])


def test_the_release_boundary_re_proves_the_pair_before_the_tag() -> None:
    steps = _bridge_steps()
    proof = _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    tag = _step_index(
        steps, lambda step: str(step.get("name") or "").startswith("Create or recover"),
    )

    assert proof < tag, "the tag is the first irreversible act"
    # Unconditional, and against trunk: both trunks move between a landing
    # and a release, so an earlier proof cannot be assumed to describe this
    # pair, and a companion selection has no place at release time.
    assert "if" not in steps[proof]
    assert "--applies-when-changed-since" not in str(steps[proof]["run"])
    assert "--consumer-ref" not in str(steps[proof]["run"])


def test_promotion_is_bound_to_the_revision_the_proof_actually_read() -> None:
    # A proven consumer head is only worth as much as the release that ships
    # it: promotion refuses when the trunk revision it is about to
    # incorporate is not the one the pre-tag proof built against.
    steps = _bridge_steps()
    proof = steps[
        _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    ]
    promotion = steps[
        _step_index(steps, lambda step: "yoke-release-promote.yml" in str(step.get("run", "")))
    ]

    proof_id = proof["id"]
    binding = promotion["env"]["PROVEN_CONSUMER_SHA"]
    assert f"steps.{proof_id}.outputs.proven_consumer_sha" in binding
    assert 'proven_consumer_sha=$PROVEN_CONSUMER_SHA' in str(promotion["run"])
