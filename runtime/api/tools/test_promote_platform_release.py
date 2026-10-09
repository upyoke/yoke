"""Promotion is retried only when it refused a trunk that moved after follow."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest

from runtime.api.tools import promote_platform_release as promote
from runtime.api.tools.follow_moved_platform_consumer import MOVED_AGAIN

CANDIDATE = "a" * 40
PROVEN = "b" * 40
MOVED = "c" * 40
ARGS = [
    "--candidate-sha",
    CANDIDATE,
    "--proven-consumer-sha",
    PROVEN,
    "--product-ref",
    "v0.1.1+launch.600",
    "--release-mode",
    "normal",
    "--target-environment",
    "prod",
    "--request-id",
    "bridge:1:1:outer",
]


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    follows: List[Tuple[int, str, str]],
    verdicts: List[str],
    refusal_regions: List[str],
) -> Dict[str, List[Any]]:
    calls: Dict[str, List[Any]] = {"follow": [], "trigger": [], "failed_log": []}

    def _follow(candidate, proven, *, timeout_sec):  # type: ignore[no-untyped-def]
        calls["follow"].append(proven)
        return follows.pop(0)

    def _yoke(argv, *, timeout):  # type: ignore[no-untyped-def]
        if argv[:2] == ["github-actions", "trigger"]:
            calls["trigger"].append(list(argv))
            return 0, f"{700 + len(calls['trigger'])}\n", ""
        if argv[:2] == ["github-actions", "wait-run"]:
            state = verdicts.pop(0)
            return 0, json.dumps({"result": {"state": state, "conclusion": state}}), ""
        if argv[:2] == ["github-actions", "failed-log"]:
            calls["failed_log"].append(argv[3])
            region = refusal_regions.pop(0)
            return 0, json.dumps({"result": {"jobs": [{"region": region}]}}), ""
        raise AssertionError(argv)

    monkeypatch.setattr(promote, "follow", _follow)
    monkeypatch.setattr(promote, "_yoke", _yoke)
    monkeypatch.setattr(
        promote,
        "_write_output",
        lambda key, value: calls.setdefault("output", []).append((key, value)),
    )
    return calls


def _input(argv: List[str], key: str) -> str:
    return next(a.split("=", 1)[1] for a in argv if a.startswith(f"{key}="))


def test_the_followed_revision_is_what_promotion_is_handed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(
        monkeypatch,
        follows=[(0, "moved", MOVED)],
        verdicts=["success"],
        refusal_regions=[],
    )

    assert promote.main(ARGS) == 0
    (trigger,) = calls["trigger"]
    assert _input(trigger, "proven_consumer_sha") == MOVED
    assert _input(trigger, "target_environment") == "prod"
    assert trigger[trigger.index("--request-id") + 1] == "bridge:1:1:outer"
    assert calls["output"] == [("run_id", "701")]


def test_a_refusal_naming_the_handed_revision_retries_with_a_fresh_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = (
        "::error title=release-input::this promotion incorporates Platform main "
        f"{'e' * 40}, but the pair was proven at {PROVEN}."
    )
    calls = _wire(
        monkeypatch,
        follows=[(0, "same", PROVEN), (0, "moved", MOVED)],
        verdicts=["failed", "success"],
        refusal_regions=[refusal],
    )

    assert promote.main(ARGS) == 0
    assert calls["follow"] == [PROVEN, PROVEN]
    first, second = calls["trigger"]
    assert _input(second, "proven_consumer_sha") == MOVED
    assert second[second.index("--request-id") + 1] == "bridge:1:1:outer:follow-2"
    assert first[first.index("--request-id") + 1] == "bridge:1:1:outer"
    assert calls["output"] == [("run_id", "702")]


def test_any_other_promotion_failure_is_reported_not_repeated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _wire(
        monkeypatch,
        follows=[(0, "same", PROVEN)],
        verdicts=["failed"],
        refusal_regions=["deploy step failed"],
    )

    assert promote.main(ARGS) == 1
    assert len(calls["trigger"]) == 1
    assert "did not succeed" in capsys.readouterr().err


def test_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = f"but the pair was proven at {PROVEN}."
    calls = _wire(
        monkeypatch,
        follows=[(0, "same", PROVEN)] * promote.MAX_ATTEMPTS,
        verdicts=["failed"] * promote.MAX_ATTEMPTS,
        refusal_regions=[refusal] * promote.MAX_ATTEMPTS,
    )

    assert promote.main(ARGS) == 1
    assert len(calls["trigger"]) == promote.MAX_ATTEMPTS
    # The last attempt's failure is final, so its log is never consulted.
    assert len(calls["failed_log"]) == promote.MAX_ATTEMPTS - 1


def test_a_trunk_still_moving_during_reproof_follows_again_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(
        monkeypatch,
        follows=[(MOVED_AGAIN, "moved again", ""), (0, "moved", MOVED)],
        verdicts=["success"],
        refusal_regions=[],
    )

    assert promote.main(ARGS) == 0
    assert len(calls["trigger"]) == 1
    assert _input(calls["trigger"][0], "proven_consumer_sha") == MOVED


def test_a_refused_follow_dispatches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _wire(
        monkeypatch,
        follows=[(1, "rewritten", "")],
        verdicts=[],
        refusal_regions=[],
    )

    assert promote.main(ARGS) == 1
    assert calls["trigger"] == []


def test_a_lost_dispatch_response_is_recovered_under_the_same_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: List[List[str]] = []
    answers = [(1, "", "workflow_dispatch_ambiguous"), (0, "801\n", "")]

    def _yoke(argv, *, timeout):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return answers.pop(0)

    monkeypatch.setattr(promote, "_yoke", _yoke)
    monkeypatch.setattr(promote.time, "sleep", lambda seconds: None)

    run_id, error = promote.dispatch({"product_ref": "v1"}, "bridge:1:1:outer")

    assert (run_id, error) == ("801", "")
    assert seen[0] == seen[1]


def test_an_unroutable_environment_is_refused_before_anything_runs() -> None:
    with pytest.raises(SystemExit):
        promote.main([*ARGS[:-4], "--target-environment", "production", *ARGS[-2:]])
