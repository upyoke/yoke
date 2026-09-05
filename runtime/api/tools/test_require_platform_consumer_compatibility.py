"""The publication guard refuses everything short of real consumer proof.

The failure it exists to prevent is a producer-only green run: the product
declared a new universe app contract, its own suite passed, and the host
implementing the previous contract only found out during promotion — after
the artifact was already published. So the cases that matter are negative.
A refused pair, absent proof, and proof that cannot be attributed to this
candidate must each stop the release rather than pass quietly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from yoke_core.domain.yaml_helper import load_document

from runtime.api.tools import require_platform_consumer_compatibility as gate

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_BRIDGE = REPO_ROOT / ".github" / "workflows" / "platform-release-bridge.yml"
GATE_MODULE = "runtime.api.tools.require_platform_consumer_compatibility"

CANDIDATE = "a" * 40
CONSUMER_REVISION = "b" * 40


def _recorder(seen: List[List[str]]):
    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, "9001\n", ""

    return _record


def _bridge_steps() -> List[Dict[str, Any]]:
    workflow = load_document(RELEASE_BRIDGE)
    return workflow["jobs"]["dispatch-platform-release"]["steps"]


def _step_index(steps: List[Dict[str, Any]], predicate) -> int:
    return next(index for index, step in enumerate(steps) if predicate(step))


def test_the_known_contract_mismatch_stops_the_release() -> None:
    # The live shape: the host refuses the bundle's declared contract. That
    # must be terminal before publication, and it must name both sides so a
    # reader knows which pair failed.
    code, narrative, proven = gate.classify(
        {
            "state": "failed",
            "conclusion": "failure",
            "head_sha": CONSUMER_REVISION,
            "html_url": "https://example.invalid/run/2",
        },
        candidate_sha=CANDIDATE,
        run_id="2",
    )

    assert code == gate.UNPROVEN
    assert proven == ""
    assert CANDIDATE in narrative
    assert CONSUMER_REVISION in narrative
    assert "companion item" in narrative
    assert "never waives adapting it" in narrative


def test_a_valid_candidate_pair_publishes_and_names_both_identities() -> None:
    code, narrative, proven = gate.classify(
        {
            "state": "success",
            "conclusion": "success",
            "head_sha": CONSUMER_REVISION,
            "html_url": "https://example.invalid/run/1",
        },
        candidate_sha=CANDIDATE,
        run_id="1",
    )

    assert code == 0
    assert proven == CONSUMER_REVISION
    assert CANDIDATE in narrative
    assert CONSUMER_REVISION in narrative


def test_success_that_names_no_revision_is_unproven_not_proven() -> None:
    code, narrative, proven = gate.classify(
        {"state": "success", "conclusion": "success", "head_sha": ""},
        candidate_sha=CANDIDATE,
        run_id="3",
    )

    assert code == gate.UNPROVEN
    assert proven == ""
    assert "names no revision it proved" in narrative


def test_a_run_that_never_concluded_leaves_the_candidate_unpublished() -> None:
    code, narrative, proven = gate.classify(
        {"state": "timeout", "html_url": "https://example.invalid/run/4"},
        candidate_sha=CANDIDATE,
        run_id="4",
    )

    assert code == gate.UNAVAILABLE
    assert proven == ""
    assert "wait budget" in narrative


def test_an_unreadable_verdict_is_unavailable_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate,
        "_yoke",
        lambda argv, *, timeout, stdin=None: (1, "not json", "relay down"),
    )

    result, unreadable = gate.await_verdict("7", timeout_sec=1)

    assert result == {}
    assert "unreadable" in unreadable


def test_one_candidate_can_never_adopt_another_candidate_s_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, "attempt-1")
    gate.dispatch("c" * 40, "attempt-1")

    request_ids = [argv[argv.index("--request-id") + 1] for argv in seen]
    assert request_ids[0] != request_ids[1]
    assert CANDIDATE in request_ids[0]
    assert seen[0][seen[0].index("--input") + 1] == (
        f"{gate.CANDIDATE_INPUT}={CANDIDATE}"
    )
    for argv in seen:
        assert argv[argv.index("--ref") + 1] == gate.CONSUMER_TRUNK_REF


def test_the_gate_reuses_the_consumer_s_own_required_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bespoke compatibility workflow would be a second definition of
    # compatible. The consumer's existing required check already builds its
    # host; a candidate commit only redirects what it builds against.
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, "attempt-1")

    assert gate.CONSUMER_CHECK_WORKFLOW == "platform-release-pin-check.yml"
    assert seen[0][seen[0].index("trigger") + 2] == gate.CONSUMER_CHECK_WORKFLOW


def test_the_same_candidate_and_attempt_rejoin_one_consumer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, "attempt-1")
    gate.dispatch(CANDIDATE, "attempt-1")

    assert len({argv[argv.index("--request-id") + 1] for argv in seen}) == 1


def test_a_missing_scoped_credential_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)

    unavailable = gate.bind_consumer_authority()

    assert gate.CONSUMER_TOKEN_ENV in unavailable


def test_a_short_candidate_sha_is_refused_before_anything_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proved = {"called": False}

    def _prove(*_args: Any, **_kwargs: Any):
        proved["called"] = True
        return 0, "proven", CONSUMER_REVISION

    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(gate, "prove", _prove)

    code = gate.main(["--candidate-sha", "abc1234", "--dispatch-key", "k"])

    assert code == gate.UNAVAILABLE
    assert proved["called"] is False


def test_a_proof_with_no_attempt_key_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    code = gate.main(["--candidate-sha", CANDIDATE, "--dispatch-key", "  "])

    assert code == gate.UNAVAILABLE


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


def test_promotion_is_bound_to_the_revision_the_proof_actually_read() -> None:
    steps = _bridge_steps()
    proof = steps[
        _step_index(steps, lambda step: GATE_MODULE in str(step.get("run", "")))
    ]
    promotion = steps[
        _step_index(
            steps, lambda step: "yoke-release-promote.yml" in str(step.get("run", "")),
        )
    ]

    binding = promotion["env"]["PROVEN_CONSUMER_SHA"]
    assert f"steps.{proof['id']}.outputs.proven_consumer_sha" in binding
    assert "proven_consumer_sha=$PROVEN_CONSUMER_SHA" in str(promotion["run"])
