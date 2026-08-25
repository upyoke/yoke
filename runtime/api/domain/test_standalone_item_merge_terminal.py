"""Close-out reaches the terminal transition holding its own authority.

A merge that crashed after its pull request landed left the item merged but
not done twice over: the transition refused because the crashed close-out had
already released the work claim, and the follow-up acquire refused because a
concurrent closer had meanwhile moved the item to ``done``. Both are recovered
here, and neither turns the ordinary refusal path into a second opinion.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
LANE = LandedLane(
    branch="ITEM-1", target="main", commit_sha=LANE_SHA, merge_sha=MERGE_SHA,
)


def _transitions(monkeypatch) -> list:
    calls: list = []

    def dispatch(*, function_id, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(terminal, "call_dispatcher", dispatch)
    return calls


def test_an_item_already_terminal_owes_nothing(monkeypatch):
    monkeypatch.setattr(
        terminal,
        "call_dispatcher",
        lambda **_k: pytest.fail("a done item must not transition again"),
    )
    monkeypatch.setattr(
        terminal.git,
        "is_landed",
        lambda *_a: pytest.fail("a done item needs no landing proof"),
    )

    assert terminal.transition_to_done(
        item_id=7, source_status="done", repo_root="/repo", lane=LANE,
    ) == ""


def test_a_lost_claim_is_recovered_before_the_transition(monkeypatch):
    """The crashed close-out released it; the landing proves it is ours."""
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        terminal.recovery, "claim_error", lambda *_a: "no live work claim on this item",
    )
    recovered: list = []
    monkeypatch.setattr(
        terminal.recovery,
        "reacquire_landed_claim",
        lambda **kwargs: (recovered.append(kwargs["lane"]), (LANE, ""))[1],
    )
    calls = _transitions(monkeypatch)

    assert terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
        session_id="session-1",
    ) == ""
    assert recovered == [LANE]
    assert [name for name, _payload in calls] == ["lifecycle.transition.execute"]


def test_a_concurrent_closer_that_finished_first_is_the_outcome(monkeypatch):
    """Recovery refuses a terminal item; the item being done is the answer."""
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "no live work claim")
    monkeypatch.setattr(
        terminal.recovery,
        "reacquire_landed_claim",
        lambda **_k: (None, "INVALID_CLAIM: item is already terminal"),
    )
    monkeypatch.setattr(
        terminal.evidence,
        "authoritative_status_is",
        lambda _item_id, expected: expected == "done",
    )
    monkeypatch.setattr(
        terminal,
        "call_dispatcher",
        lambda **_k: pytest.fail("a closed-out item must not transition again"),
    )

    assert terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    ) == ""


def test_unrecoverable_authority_names_the_landing_it_could_not_close(
    monkeypatch,
):
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "held elsewhere")
    monkeypatch.setattr(
        terminal.recovery,
        "reacquire_landed_claim",
        lambda **_k: (None, "work claim held by another session"),
    )
    monkeypatch.setattr(
        terminal.evidence, "authoritative_status_is", lambda *_a: False,
    )
    monkeypatch.setattr(
        terminal,
        "call_dispatcher",
        lambda **_k: pytest.fail("no authority means no transition"),
    )

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    )

    assert "the merge is landed" in error
    assert "another session" in error


def test_an_unlanded_merge_identity_is_still_refused(monkeypatch):
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: False)
    monkeypatch.setattr(
        terminal.recovery,
        "claim_error",
        lambda *_a: pytest.fail("an unlanded merge is refused before authority"),
    )

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    )

    assert "not reachable from 'main'" in error
