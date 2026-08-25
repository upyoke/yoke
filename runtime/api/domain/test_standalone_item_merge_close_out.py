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

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
LANE = landed.LandedLane(
    branch="ITEM-1",
    target="main",
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("a.py",),
    source="lane branch",
)


def _transition_calls(monkeypatch) -> list:
    """Capture every close-out call, whichever module makes it."""
    calls: list = []

    def dispatch(*, function_id, target, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    monkeypatch.setattr(terminal, "call_dispatcher", dispatch)
    # This session holds its claim; the recovery path has its own coverage.
    monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "")
    return calls


def test_transition_accepts_a_landing_only_the_remote_has_seen(monkeypatch):
    """A queue merge lands on GitHub; the local base branch lags behind."""
    fetched: list = []

    def is_landed(repo_root, commit, target):
        fetched.append((commit, target))
        return commit == LANE_SHA

    monkeypatch.setattr(terminal.git, "is_landed", is_landed)
    calls = _transition_calls(monkeypatch)

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    )

    assert error == ""
    assert fetched[0] == (LANE_SHA, "main")
    assert calls[0][0] == "lifecycle.transition.execute"


def test_transition_accepts_the_merge_commit_when_the_lane_head_was_rewritten(
    monkeypatch,
):
    """A squash or queue merge can leave only the merge commit reachable."""
    monkeypatch.setattr(
        terminal.git,
        "is_landed",
        lambda repo_root, commit, target: commit == MERGE_SHA,
    )
    calls = _transition_calls(monkeypatch)

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    )

    assert error == ""
    assert calls[0][1]["target_status"] == "done"


def test_transition_still_refuses_a_commit_no_branch_carries(monkeypatch):
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_args: False)

    def forbidden(**_kw):
        raise AssertionError("an unlanded commit must not transition")

    monkeypatch.setattr(terminal, "call_dispatcher", forbidden)

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root="/repo",
        lane=LANE,
    )

    assert "is not reachable from 'main'" in error


def test_a_queue_landed_item_closes_out_with_its_own_file_set(monkeypatch):
    """A landed merge must not strand at the evidence write.

    The queue route returned no touched files, so the evidence writer
    refused every queue-landed item after its branch had already merged.
    The file set travels back with the landing outcome for exactly this
    call, whichever boundary produced it.
    """
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/.worktrees/ITEM-1", "branch": "ITEM-1"}],
    }
    monkeypatch.setattr(
        merge_cli,
        "_resolve_item",
        lambda ref, project: (item, ""),
    )
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda item, target: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        verify,
        "qa_preflight",
        lambda item, *, item_ref, repo_root, branch: (LANE_SHA, ""),
    )
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_kw: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py", "docs/b.md"),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_args: True)
    calls = _transition_calls(monkeypatch)

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "merge_group green"],
    )

    assert exit_code == 0
    payloads = dict(calls)
    evidence = payloads["direct_workflow.dash.evidence"]
    assert evidence["touched_files"] == ["a.py", "docs/b.md"]
    assert evidence["commit_sha"] == LANE_SHA
    assert evidence["merge_sha"] == MERGE_SHA
    assert payloads["lifecycle.transition.execute"]["target_status"] == "done"
    call_names = [name for name, _payload in calls]
    assert call_names.index("direct_workflow.dash.evidence") < call_names.index(
        "lifecycle.transition.execute"
    )


def test_landed_lane_reacquires_close_out_authority(monkeypatch):
    """A retry takes a replacement claim only for a proven landing."""
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, result={"claim_id": 9}, error=None)

    monkeypatch.setattr(recovery, "call_dispatcher", dispatch)

    recovered, error = recovery.reacquire_landed_claim(
        item_id=7, session_id="session-1", lane=LANE,
    )

    assert error == ""
    assert recovered == LANE
    assert calls[0]["function_id"] == "claims.work.acquire"
    assert calls[0]["actor"].session_id == "session-1"


def test_absent_landing_cannot_reacquire_close_out_authority(monkeypatch):
    """Without a landing the claim refusal is the caller's own, unchanged."""
    monkeypatch.setattr(
        recovery,
        "call_dispatcher",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("an unlanded lane cannot acquire a claim")
        ),
    )
    monkeypatch.setattr(recovery, "claim_error", lambda *_a: "")

    recovered, error = recovery.reacquire_landed_claim(
        item_id=7, session_id="session-1", lane=None,
    )

    assert recovered is None
    assert "no landing the base branch contains" in error


def test_merge_retry_uses_recovered_head_then_finishes_close_out(monkeypatch):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(
        merge_cli,
        "_session_holds_claim",
        lambda *_a: "no live work claim on this item",
    )
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        recovery,
        "reacquire_landed_claim",
        lambda **_k: (LANE, ""),
    )
    preflight_heads = []

    def preflight(recovered_item, **_kwargs):
        preflight_heads.append(recovered_item["worktrees"][-1]["commit_sha"])
        return LANE_SHA, ""

    monkeypatch.setattr(verify, "qa_preflight", preflight)
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=True,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda _item_id: None)
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: True)
    calls = _transition_calls(monkeypatch)

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "green"],
    )

    assert exit_code == 0
    assert preflight_heads == [LANE_SHA]
    assert [name for name, _payload in calls][-2:] == [
        "direct_workflow.dash.evidence",
        "lifecycle.transition.execute",
    ]


def test_is_landed_consults_the_remote_before_refusing(monkeypatch):
    commands: list = []

    def fake_git(repo_root, *args):
        commands.append(list(args))
        landed = args[:2] == ("merge-base", "--is-ancestor")
        remote_ref = landed and args[3] == "origin/main"
        return SimpleNamespace(
            returncode=0 if remote_ref else 1,
            stdout="origin\n",
            stderr="",
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
