"""The release bridge proves the pair before its tag and promotes that proof.

These read the bridge workflow itself: the proof step runs before the first
irreversible act, keys only on the exact pair, receives an explicit consumer
commit, and hands promotion the revision it actually proved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_core.domain.yaml_helper import load_document

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_BRIDGE = REPO_ROOT / ".github" / "workflows" / "platform-release-bridge.yml"
GATE_MODULE = "runtime.api.tools.require_platform_consumer_compatibility"


def _bridge_steps() -> List[Dict[str, Any]]:
    workflow = load_document(RELEASE_BRIDGE)
    return workflow["jobs"]["dispatch-platform-release"]["steps"]


def _step_index(steps: List[Dict[str, Any]], predicate) -> int:
    return next(index for index, step in enumerate(steps) if predicate(step))


def test_the_bridge_does_not_key_proof_on_the_caller_attempt() -> None:
    steps = _bridge_steps()
    proof = steps[
        _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    ]
    run = str(proof.get("run", ""))

    assert "--dispatch-key" not in run
    assert "GITHUB_RUN_ID" not in run
    assert "GITHUB_RUN_ATTEMPT" not in run


def test_the_release_proves_the_pair_before_the_tag() -> None:
    steps = _bridge_steps()
    proof = _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    tag = _step_index(
        steps,
        lambda step: str(step.get("name") or "").startswith("Create or recover"),
    )

    assert proof < tag, "the tag is the first irreversible act"
    # Unconditional: a release publishes whatever trunk now carries, so
    # there is no diff for this gate to consult and nothing to skip on.
    assert "if" not in steps[proof]


def test_the_release_step_receives_an_explicit_consumer_sha() -> None:
    steps = _bridge_steps()
    proof = steps[
        _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    ]

    assert "--consumer-sha" in str(proof.get("run", ""))
    assert proof.get("env", {}).get("CONSUMER_SHA") == "${{ inputs.consumer_sha }}"


def test_promotion_is_bound_to_the_revision_the_proof_actually_read() -> None:
    steps = _bridge_steps()
    proof = steps[
        _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    ]
    promotion = steps[
        _step_index(
            steps,
            lambda step: "promote_platform_release" in str(step.get("run", "")),
        )
    ]

    binding = promotion["env"]["PROVEN_CONSUMER_SHA"]
    assert f"steps.{proof['id']}.outputs.proven_consumer_sha" in binding
    assert '--proven-consumer-sha "$PROVEN_CONSUMER_SHA"' in str(promotion["run"])
