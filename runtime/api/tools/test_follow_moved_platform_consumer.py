"""Promotion ships the consumer revision that was proven, even after a move.

The live failure: the pre-tag proof built the consumer against the release
candidate, the consumer trunk then moved during the factory waits, and the
promotion refused the pair because the trunk carried changes past the proven
commit. The bridge now re-reads that trunk right before it dispatches.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from runtime.api.tools import follow_moved_platform_consumer as follow_mod
from runtime.api.tools import require_platform_consumer_compatibility as gate

CANDIDATE = "a" * 40
PROVEN = "b" * 40
MOVED = "c" * 40
FURTHER = "d" * 40


def _trunk(head: str, relation: str) -> str:
    return json.dumps(
        {"success": True, "result": {"head_sha": head, "relation": relation}}
    )


@pytest.fixture
def bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(follow_mod, "bind_consumer_authority", lambda: "")


def _reads(monkeypatch: pytest.MonkeyPatch, answers: List[str]) -> List[List[str]]:
    seen: List[List[str]] = []

    def _yoke(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 0, answers.pop(0), ""

    monkeypatch.setattr(follow_mod, "_yoke", _yoke)
    return seen


def _proofs(
    monkeypatch: pytest.MonkeyPatch,
    results: Dict[str, Any],
) -> List[str]:
    proved: List[str] = []

    def _prove(candidate, consumer, *, timeout_sec):  # type: ignore[no-untyped-def]
        assert candidate == CANDIDATE
        proved.append(consumer)
        return results[consumer]

    monkeypatch.setattr(follow_mod, "prove", _prove)
    return proved


def test_an_unchanged_trunk_hands_on_the_proven_revision_without_reproof(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    seen = _reads(monkeypatch, [_trunk(PROVEN, "identical")])
    proved = _proofs(monkeypatch, {})

    code, _, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha, proved) == (0, PROVEN, [])
    assert seen == [
        [
            "github",
            "branch",
            "head",
            "main",
            "--since",
            PROVEN,
            "--project",
            "platform",
            "--json",
        ]
    ]


def test_a_trunk_that_moved_forward_is_proven_again_and_handed_on(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    _reads(monkeypatch, [_trunk(MOVED, "descendant")])
    proved = _proofs(monkeypatch, {MOVED: (0, "proven", MOVED)})

    code, _, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha, proved) == (0, MOVED, [MOVED])


def test_a_rewritten_trunk_refuses_by_name_without_proving_anything(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    _reads(monkeypatch, [_trunk(MOVED, "not_descendant")])
    proved = _proofs(monkeypatch, {})

    code, narrative, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha, proved) == (gate.UNPROVEN, "", [])
    assert "does not descend from the proven" in narrative
    assert MOVED in narrative and PROVEN in narrative
    assert "start a new deployment run" in narrative


def test_a_refused_reproof_of_the_moved_trunk_stays_refused(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    _reads(monkeypatch, [_trunk(MOVED, "descendant"), _trunk(MOVED, "identical")])
    _proofs(monkeypatch, {MOVED: (gate.UNPROVEN, "the hosted consumer refused", "")})

    code, narrative, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha) == (gate.UNPROVEN, "")
    assert "refused" in narrative


def test_a_trunk_that_moves_again_during_reproof_asks_for_another_attempt(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    _reads(monkeypatch, [_trunk(MOVED, "descendant"), _trunk(FURTHER, "descendant")])
    _proofs(monkeypatch, {MOVED: (gate.UNPROVEN, "stale pair", "")})

    code, narrative, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha) == (follow_mod.MOVED_AGAIN, "")
    assert FURTHER in narrative


def test_a_control_plane_without_the_trunk_read_keeps_the_proven_revision(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    refusal = json.dumps({"success": False, "error": {"code": "function_version_skew"}})
    seen: List[List[str]] = []

    def _yoke(argv, *, timeout, stdin=None):  # type: ignore[no-untyped-def]
        seen.append(list(argv))
        return 1, refusal, ""

    monkeypatch.setattr(follow_mod, "_yoke", _yoke)
    proved = _proofs(monkeypatch, {})

    code, narrative, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha, proved) == (0, PROVEN, [])
    assert "consumer_trunk_unread" in narrative


def test_any_other_unreadable_trunk_stops_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    bound: None,
) -> None:
    refusal = json.dumps({"success": False, "error": {"code": "auth_failed"}})
    monkeypatch.setattr(
        follow_mod,
        "_yoke",
        lambda argv, *, timeout, stdin=None: (1, refusal, ""),
    )

    code, narrative, sha = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, sha) == (gate.UNAVAILABLE, "")
    assert "nothing has been dispatched" in narrative


def test_missing_consumer_authority_stops_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(follow_mod, "bind_consumer_authority", lambda: "no token")
    seen = _reads(monkeypatch, [])

    code, narrative, _ = follow_mod.follow(CANDIDATE, PROVEN, timeout_sec=60)

    assert (code, seen) == (gate.UNAVAILABLE, [])
    assert "no token" in narrative
