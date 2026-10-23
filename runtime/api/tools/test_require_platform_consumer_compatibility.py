"""The publication guard refuses everything short of real consumer proof.

The failure it exists to prevent is a producer-only green run: the product
declared a new universe app contract, its own suite passed, and the host
implementing the previous contract only found out during promotion — after
the artifact was already published. So the cases that matter are negative.
A refused pair, absent proof, and proof that cannot be attributed to this
candidate must each stop the release rather than pass quietly.
"""

from __future__ import annotations

from typing import Any, List
import json

import pytest

from runtime.api.tools import require_platform_consumer_compatibility as gate


CANDIDATE = "a" * 40
CONSUMER_REVISION = "b" * 40


def _recorder(seen: List[List[str]]):
    def _record(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        if argv[1:3] == ["dispatch-tag", "ensure"]:
            return (
                0,
                json.dumps(
                    {
                        "success": True,
                        "result": {
                            "repo": argv[3],
                            "tag": argv[4],
                            "sha": argv[5],
                        },
                    }
                ),
                "",
            )
        seen.append(list(argv))
        return 0, "9001\n", ""

    return _record


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
        consumer_sha=CONSUMER_REVISION,
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
        consumer_sha=CONSUMER_REVISION,
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
        consumer_sha=CONSUMER_REVISION,
        run_id="3",
    )

    assert code == gate.UNPROVEN
    assert proven == ""
    assert "names no revision it proved" in narrative


def test_success_against_a_different_consumer_commit_is_unproven() -> None:
    # The named branch can move past the bound commit between binding and
    # dispatch; the recovery names a fresh run, never a mutated retry of the
    # same pair (which `--retry-of` lineage could not carry anyway).
    code, narrative, proven = gate.classify(
        {
            "state": "success",
            "conclusion": "success",
            "head_sha": CONSUMER_REVISION,
            "html_url": "https://example.invalid/run/9",
        },
        candidate_sha=CANDIDATE,
        consumer_sha="c" * 40,
        run_id="9",
    )

    assert code == gate.UNPROVEN
    assert proven == ""
    assert "stale pair" in narrative
    assert "start a new deployment run" in narrative
    assert "fresh consumer commit" in narrative
    assert "c" * 40 in narrative
    assert CONSUMER_REVISION in narrative


def test_a_run_that_never_concluded_leaves_the_candidate_unpublished() -> None:
    code, narrative, proven = gate.classify(
        {"state": "timeout", "html_url": "https://example.invalid/run/4"},
        candidate_sha=CANDIDATE,
        consumer_sha=CONSUMER_REVISION,
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

    gate.dispatch(CANDIDATE, CONSUMER_REVISION)
    gate.dispatch("c" * 40, CONSUMER_REVISION)

    request_ids = [argv[argv.index("--request-id") + 1] for argv in seen]
    assert request_ids[0] != request_ids[1]
    assert CANDIDATE in request_ids[0]
    assert seen[0][seen[0].index("--input") + 1] == (
        f"{gate.CANDIDATE_INPUT}={CANDIDATE}"
    )
    for argv in seen:
        assert argv[argv.index("--ref") + 1] == (
            f"yoke-deploy/consumer-{CONSUMER_REVISION}"
        )
        assert argv[argv.index("--request-id") + 1].endswith(
            gate.CONSUMER_CHECK_WORKFLOW
        )


def test_a_different_consumer_commit_is_a_different_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, CONSUMER_REVISION)
    gate.dispatch(CANDIDATE, "c" * 40)

    request_ids = [argv[argv.index("--request-id") + 1] for argv in seen]
    assert request_ids[0] != request_ids[1]
    assert CONSUMER_REVISION in request_ids[0]
    assert seen[1][seen[1].index("--ref") + 1] == f"yoke-deploy/consumer-{'c' * 40}"


def test_the_gate_reuses_the_consumer_s_own_required_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bespoke compatibility workflow would be a second definition of
    # compatible. The consumer's existing required check already builds its
    # host; a candidate commit only redirects what it builds against.
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, CONSUMER_REVISION)

    assert gate.CONSUMER_CHECK_WORKFLOW == "platform-release-pin-check.yml"
    assert seen[0][seen[0].index("trigger") + 2] == gate.CONSUMER_CHECK_WORKFLOW


_PENDING = (1, "", "error (workflow_dispatch_pending): run not listed")


def _clock(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    now = {"t": 0.0}
    slept: List[float] = []

    def _sleep(seconds: float) -> None:
        slept.append(seconds)
        now["t"] += float(seconds)

    monkeypatch.setattr(gate.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(gate.time, "sleep", _sleep)
    return slept


def _script(outcomes: List[tuple], calls: List[List[str]]):
    def _yoke(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        if argv[1:3] == ["dispatch-tag", "ensure"]:
            receipt = {"success": True, "result": {"repo": argv[3], "tag": argv[4], "sha": argv[5]}}
            return 0, json.dumps(receipt), ""
        calls.append(list(argv))
        return outcomes.pop(0)

    return _yoke


def test_a_pending_join_retries_and_returns_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept = _clock(monkeypatch)
    calls: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _script([_PENDING, (0, "9001\n", "")], calls))
    run_id, error = gate.dispatch(CANDIDATE, CONSUMER_REVISION)
    assert (run_id, error, slept) == ("9001", "", [2.0])
    ids = {argv[argv.index("--request-id") + 1] for argv in calls}
    assert len(calls) == 2 and len(ids) == 1


def test_a_pending_join_past_the_budget_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept = _clock(monkeypatch)
    calls: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _script([_PENDING] * 20, calls))
    code, narrative, proven = gate.prove_pair(CANDIDATE, CONSUMER_REVISION, timeout_sec=1)
    assert (code, proven) == (gate.UNAVAILABLE, "")
    assert "could not be dispatched" in narrative
    assert "unproven:" in narrative and "workflow_dispatch_pending" in narrative
    assert sum(slept) == gate._PENDING_JOIN_BUDGET_SECONDS
    ids = {argv[argv.index("--request-id") + 1] for argv in calls}
    assert len(calls) > 1 and len(ids) == 1


def test_a_dispatch_error_other_than_pending_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept = _clock(monkeypatch)
    calls: List[List[str]] = []
    refused = (1, "", "error (workflow_dispatch_scope_required): missing")
    monkeypatch.setattr(gate, "_yoke", _script([refused], calls))
    run_id, error = gate.dispatch(CANDIDATE, CONSUMER_REVISION)
    assert run_id == "" and slept == [] and len(calls) == 1
    assert "could not be dispatched" in error
    assert "workflow_dispatch_scope_required" in error


def test_the_same_pair_rejoins_one_consumer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []
    monkeypatch.setattr(gate, "_yoke", _recorder(seen))

    gate.dispatch(CANDIDATE, CONSUMER_REVISION)
    gate.dispatch(CANDIDATE, CONSUMER_REVISION)

    assert len({argv[argv.index("--request-id") + 1] for argv in seen}) == 1


def test_a_missing_scoped_credential_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)

    unavailable = gate.bind_consumer_authority()

    assert gate.CONSUMER_TOKEN_ENV in unavailable
    assert "CI-only" in unavailable
    assert "yoke github-actions trigger" in unavailable
    assert "nothing can reach" not in unavailable


def test_a_short_candidate_sha_is_refused_before_anything_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proved = {"called": False}

    def _prove(*_args: Any, **_kwargs: Any):
        proved["called"] = True
        return 0, "proven", CONSUMER_REVISION

    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(gate, "prove", _prove)

    code = gate.main(
        [
            "--candidate-sha",
            "abc1234",
            "--consumer-sha",
            CONSUMER_REVISION,
        ]
    )

    assert code == gate.UNAVAILABLE
    assert proved["called"] is False


def test_a_short_consumer_sha_is_refused_before_anything_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proved = {"called": False}

    def _prove(*_args: Any, **_kwargs: Any):
        proved["called"] = True
        return 0, "proven", CONSUMER_REVISION

    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(gate, "prove", _prove)

    code = gate.main(
        [
            "--candidate-sha",
            CANDIDATE,
            "--consumer-sha",
            "short",
        ]
    )

    assert code == gate.UNAVAILABLE
    assert proved["called"] is False
