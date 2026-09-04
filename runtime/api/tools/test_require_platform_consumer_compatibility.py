"""The consumer-compatibility gate refuses everything short of real proof.

The failure this gate exists to prevent is a producer-only green run: the
product declared a new universe app contract, its own suite passed, and the
host implementing the previous contract only found out during promotion.
So the cases that matter here are all negative — a refused pair, absent
proof, and proof that cannot be attributed to this candidate must each fail
the caller rather than pass quietly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from yoke_core.domain.yaml_helper import load_document

from runtime.api.tools import platform_consumer_check as consumer
from runtime.api.tools import require_platform_consumer_compatibility as gate

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE_WORKFLOW = WORKFLOWS / "yoke-consumer-compatibility.yml"
RELEASE_BRIDGE = WORKFLOWS / "platform-release-bridge.yml"
MERGE_QUEUE = REPO_ROOT / ".yoke" / "merge-queue.json"
GATE_MODULE = "runtime.api.tools.require_platform_consumer_compatibility"

CANDIDATE = "a" * 40
CONSUMER_REVISION = "b" * 40
CONTRACT_VERSION_ASSET = (
    "packages/yoke-core/src/yoke_core/ui/static/contract-version.js"
)


def _succeeded(head_sha: str = CONSUMER_REVISION) -> Dict[str, Any]:
    return {
        "state": "success",
        "conclusion": "success",
        "head_sha": head_sha,
        "html_url": "https://example.invalid/run/1",
    }


def test_the_watched_surface_is_derived_from_the_shipped_asset_contract() -> None:
    # A trigger listing paths by hand goes stale silently: the asset moves,
    # the list keeps matching nothing, and the gate never fires again.
    paths = gate.host_consumed_paths()

    assert CONTRACT_VERSION_ASSET in paths
    for path in paths:
        assert (REPO_ROOT / path).is_file(), path


def test_a_contract_change_puts_the_consumer_in_play() -> None:
    assert gate.touches_host_contract([CONTRACT_VERSION_ASSET])
    assert gate.touches_host_contract(
        ["packages/yoke-core/src/yoke_core/ui/contracts/universe-app.ts"]
    )


def test_an_unrelated_change_does_not_pay_for_a_consumer_build() -> None:
    assert gate.touches_host_contract(["docs/testing-verification.md"]) == ()


def test_an_unreadable_diff_scope_refuses_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(_root: Path, _base: str) -> Tuple[str, ...]:
        raise RuntimeError("no such ref")

    monkeypatch.setattr(gate, "changed_paths", _explode)
    applies, why = gate.applicability("origin/nowhere")

    assert applies is None
    assert "unresolvable" in why


def test_no_scope_ref_means_prove_unconditionally() -> None:
    assert gate.applicability("") == (True, "")


def test_a_refused_pair_names_both_revisions_and_the_companion_item() -> None:
    code, narrative, proven = consumer.classify(
        {
            "state": "failed",
            "conclusion": "failure",
            "head_sha": CONSUMER_REVISION,
            "html_url": "https://example.invalid/run/2",
        },
        candidate_sha=CANDIDATE,
        run_id="2",
    )

    assert code == consumer.UNPROVEN
    assert proven == ""
    assert CANDIDATE in narrative
    assert CONSUMER_REVISION in narrative
    assert "companion item" in narrative
    assert "never waives adapting it" in narrative


def test_success_that_names_no_revision_is_unproven_not_proven() -> None:
    code, narrative, proven = consumer.classify(
        _succeeded(head_sha=""), candidate_sha=CANDIDATE, run_id="3",
    )

    assert code == consumer.UNPROVEN
    assert proven == ""
    assert "names no revision it proved" in narrative


def test_a_run_that_never_concluded_is_unavailable() -> None:
    code, narrative, proven = consumer.classify(
        {"state": "timeout", "html_url": "https://example.invalid/run/4"},
        candidate_sha=CANDIDATE,
        run_id="4",
    )

    assert code == consumer.UNAVAILABLE
    assert proven == ""
    assert "wait budget" in narrative


def test_a_proven_pair_records_both_identities() -> None:
    code, narrative, proven = consumer.classify(
        _succeeded(), candidate_sha=CANDIDATE, run_id="5",
    )

    assert code == 0
    assert proven == CONSUMER_REVISION
    assert CANDIDATE in narrative
    assert CONSUMER_REVISION in narrative


def test_one_candidate_can_never_adopt_another_candidate_s_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []

    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, "9001\n", ""

    monkeypatch.setattr(consumer, "_yoke", _record)
    consumer.dispatch(CANDIDATE, "attempt-1")
    consumer.dispatch("c" * 40, "attempt-1")

    request_ids = [argv[argv.index("--request-id") + 1] for argv in seen]
    assert request_ids[0] != request_ids[1]
    assert CANDIDATE in request_ids[0]
    for argv in seen:
        assert argv[argv.index("--input") + 1].startswith(
            f"{consumer.CANDIDATE_INPUT}="
        )


def test_the_same_candidate_and_attempt_rejoin_one_consumer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []

    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, "9001\n", ""

    monkeypatch.setattr(consumer, "_yoke", _record)
    consumer.dispatch(CANDIDATE, "attempt-1")
    consumer.dispatch(CANDIDATE, "attempt-1")

    request_ids = {argv[argv.index("--request-id") + 1] for argv in seen}
    assert len(request_ids) == 1


def test_a_breaking_pair_can_name_the_companion_branch_to_prove_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Trunk still implements the old contract, so a breaking change cannot be
    # proven against it. Naming the companion branch is what breaks the
    # otherwise circular ordering; the release boundary still demands trunk.
    seen: List[List[str]] = []

    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, "9001\n", ""

    monkeypatch.setattr(consumer, "_yoke", _record)
    consumer.dispatch(CANDIDATE, "attempt-1", "companion-branch")

    argv = seen[0]
    assert argv[argv.index("--ref") + 1] == "companion-branch"
    assert "companion-branch" in argv[argv.index("--request-id") + 1]


def test_the_default_is_the_consumer_trunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []

    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, "9001\n", ""

    monkeypatch.setattr(consumer, "_yoke", _record)
    consumer.dispatch(CANDIDATE, "attempt-1")

    argv = seen[0]
    assert argv[argv.index("--ref") + 1] == consumer.CONSUMER_TRUNK_REF


def test_the_companion_branch_is_read_from_the_candidate_s_own_commits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: List[Tuple[str, ...]] = []

    def _fake_git(_root: Path, *args: str) -> str:
        calls.append(args)
        if args[0] == "merge-base":
            return "base\n"
        return "adapt the host\n\nConsumer-candidate: companion-branch\n"

    monkeypatch.setattr(gate, "_git", _fake_git)

    assert gate.companion_consumer_ref(tmp_path, "origin/main") == "companion-branch"


def test_a_candidate_naming_no_companion_falls_back_to_trunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        gate, "_git", lambda _root, *args: "base\n" if args[0] == "merge-base" else "x\n",
    )

    assert gate.companion_consumer_ref(tmp_path, "origin/main") == ""


def test_a_fork_without_the_scoped_credential_is_told_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(consumer.CONSUMER_TOKEN_ENV, raising=False)

    unavailable = consumer.bind_consumer_authority()

    assert consumer.CONSUMER_TOKEN_ENV in unavailable
    assert "maintainer" in unavailable


def test_an_unreadable_verdict_is_unavailable_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        consumer,
        "_yoke",
        lambda argv, *, timeout, stdin=None: (1, "not json", "relay down"),
    )

    result, unreadable = consumer.await_verdict("7", timeout_sec=1)

    assert result == {}
    assert "unreadable" in unreadable


def _run_gate(monkeypatch: pytest.MonkeyPatch, argv: List[str]) -> Tuple[int, bool]:
    proved: Dict[str, bool] = {"called": False}

    def _prove(*_args: Any, **_kwargs: Any) -> Tuple[int, str, str]:
        proved["called"] = True
        return 0, "proven", CONSUMER_REVISION

    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(consumer, "prove", _prove)
    monkeypatch.setattr(gate.consumer, "prove", _prove)
    return gate.main(argv), proved["called"]


def test_a_short_candidate_sha_is_refused_before_anything_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, dispatched = _run_gate(
        monkeypatch, ["--candidate-sha", "abc1234", "--dispatch-key", "k"],
    )

    assert code == consumer.UNAVAILABLE
    assert dispatched is False


def test_a_proof_with_no_attempt_key_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, dispatched = _run_gate(
        monkeypatch, ["--candidate-sha", CANDIDATE, "--dispatch-key", "  "],
    )

    assert code == consumer.UNAVAILABLE
    assert dispatched is False


def test_the_gate_declares_itself_a_required_landing_check() -> None:
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    contexts = {
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    }

    assert "consumer-compatibility" in contexts


def test_the_gate_workflow_reports_on_both_landing_events() -> None:
    workflow = load_document(GATE_WORKFLOW)
    # `on` is YAML 1.1 truthy; the loader may hand it back as the bool key.
    triggers = workflow.get("on", workflow.get(True))

    assert set(triggers) == {"pull_request", "merge_group"}
    job = workflow["jobs"]["consumer_compatibility"]
    assert job["name"] == "consumer-compatibility"
    # An event filter on the job would leave the required context absent
    # rather than concluded, which strands a queue entry rather than
    # failing it.
    assert "if" not in job
    assert any(GATE_MODULE in str(step.get("run", "")) for step in job["steps"])


def test_the_release_boundary_re_proves_the_pair_before_the_tag() -> None:
    workflow = load_document(RELEASE_BRIDGE)
    steps = workflow["jobs"]["dispatch-platform-release"]["steps"]
    names = [str(step.get("name") or "") for step in steps]
    proof = next(
        index for index, step in enumerate(steps) if GATE_MODULE in str(step.get("run", ""))
    )
    tag = next(
        index for index, name in enumerate(names) if name.startswith("Create or recover")
    )

    assert proof < tag, "the tag is the first irreversible act"
    # Unconditional: both trunks move between merge and release, so the
    # earlier proof cannot be assumed to still describe this pair.
    assert "if" not in steps[proof]
