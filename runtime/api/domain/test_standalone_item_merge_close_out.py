"""A landed merge must be able to finish closing the item out.

Both close-out failures this covers left an item merged but not done: the
terminal transition refused because the local checkout had not seen the
landing, and the merge identity it was handed named a commit the landing
rewrote. Either way the merge itself had already happened, so refusing the
close-out strands the item rather than protecting anything.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_git as git

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def _transition_calls(monkeypatch) -> list:
    calls: list = []

    def dispatch(*, function_id, target, payload, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    return calls


def test_transition_accepts_a_landing_only_the_remote_has_seen(monkeypatch):
    """A queue merge lands on GitHub; the local base branch lags behind."""
    fetched: list = []

    def is_landed(repo_root, commit, target):
        fetched.append((commit, target))
        return commit == LANE_SHA

    monkeypatch.setattr(git, "is_landed", is_landed)
    calls = _transition_calls(monkeypatch)

    error = merge_cli._transition_to_done(
        7, "reviewing-implementation", Path("/repo"), "main", LANE_SHA, MERGE_SHA,
    )

    assert error == ""
    assert fetched[0] == (LANE_SHA, "main")
    assert calls[0][0] == "lifecycle.transition.execute"


def test_transition_accepts_the_merge_commit_when_the_lane_head_was_rewritten(
    monkeypatch,
):
    """A squash or queue merge can leave only the merge commit reachable."""
    monkeypatch.setattr(
        git, "is_landed",
        lambda repo_root, commit, target: commit == MERGE_SHA,
    )
    calls = _transition_calls(monkeypatch)

    error = merge_cli._transition_to_done(
        7, "reviewing-implementation", Path("/repo"), "main", LANE_SHA, MERGE_SHA,
    )

    assert error == ""
    assert calls[0][1]["target_status"] == "done"


def test_transition_still_refuses_a_commit_no_branch_carries(monkeypatch):
    monkeypatch.setattr(git, "is_landed", lambda *_args: False)

    def forbidden(**_kw):
        raise AssertionError("an unlanded commit must not transition")

    monkeypatch.setattr(merge_cli, "call_dispatcher", forbidden)

    error = merge_cli._transition_to_done(
        7, "reviewing-implementation", Path("/repo"), "main", LANE_SHA, MERGE_SHA,
    )

    assert "is not reachable from 'main'" in error


def test_is_landed_consults_the_remote_before_refusing(monkeypatch):
    commands: list = []

    def fake_git(repo_root, *args):
        commands.append(list(args))
        landed = args[:2] == ("merge-base", "--is-ancestor")
        remote_ref = landed and args[3] == "origin/main"
        return SimpleNamespace(
            returncode=0 if remote_ref else 1, stdout="origin\n", stderr="",
        )

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git, "git_out", lambda repo_root, *args: "origin")

    assert git.is_landed("/repo", LANE_SHA, "main") is True
    assert ["fetch", "origin", "main"] in commands


def test_is_landed_is_false_without_a_commit(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no git read is needed without a commit")

    monkeypatch.setattr(git, "_git", forbidden)

    assert git.is_landed("/repo", "", "main") is False
