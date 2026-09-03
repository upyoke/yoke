"""Terminal close-out sweeps earlier preserved lanes and records its own refusals."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import terminal_lane_cleanup
from yoke_core.domain.terminal_lane_cleanup import TerminalLaneCloseOut
from yoke_core.engines.merge_worktree_safe_prune import PreservedLane, WorktreeSweep


def _item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash", "terminal_stage_ids": ["done", "cancelled"]},
        "project": {"id": 1, "slug": "yoke", "default_branch": "main"},
        "claim": None,
        "worktrees": [{"branch": "ITEM-7", "path": "/repo/.worktrees/ITEM-7"}],
    }


def _no_sweep(**_kwargs) -> WorktreeSweep:
    return WorktreeSweep()


def _recording_dispatcher(calls: list[dict], *, success: bool = True):
    def dispatch(*, function_id, target, payload):
        calls.append({"function_id": function_id, "target": target, "payload": payload})
        return SimpleNamespace(
            success=success,
            result={},
            error=None if success else SimpleNamespace(message="project unknown"),
        )

    return dispatch


def test_terminal_close_out_runs_the_machine_wide_sweep(monkeypatch, tmp_path):
    """Every landing re-examines the lanes earlier landings preserved."""
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: False)
    swept: list[dict] = []

    def sweep(**kwargs):
        swept.append(kwargs)
        return WorktreeSweep(
            removed=("/repo/.worktrees/OLD",),
            preserved=(PreservedLane("/repo/.worktrees/DIRTY", "dirty or unverifiable worktree"),),
        )

    close = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        sweep=sweep,
    )

    assert swept[0]["repo_root"] == str(tmp_path.resolve())
    assert swept[0]["target"] == "main"
    assert close.sweep == {
        "removed": ["/repo/.worktrees/OLD"],
        "preserved": [
            {"path": "/repo/.worktrees/DIRTY", "reason": "dirty or unverifiable worktree"}
        ],
        "skipped": "",
    }


def test_non_terminal_transition_neither_prunes_nor_sweeps(tmp_path):
    close = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="reviewing-implementation",
        repo_root=tmp_path,
        prune=lambda **_k: pytest.fail("must not prune"),
        sweep=lambda **_k: pytest.fail("must not sweep"),
    )

    assert close == TerminalLaneCloseOut()


def _recording_dispatcher(calls: list[dict], *, success: bool = True):
    def dispatch(*, function_id, target, payload):
        calls.append({"function_id": function_id, "target": target, "payload": payload})
        return SimpleNamespace(
            success=success,
            result={},
            error=None if success else SimpleNamespace(message="project unknown"),
        )

    return dispatch


def test_preserved_own_lane_is_recorded_as_an_event(monkeypatch, tmp_path):
    """The refusal outlives the merge output: it lands on the events ledger."""
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)
    calls: list[dict] = []
    monkeypatch.setattr(terminal_lane_cleanup, "call_dispatcher", _recording_dispatcher(calls))
    reason = "lane ITEM-7 preserved: worktree is dirty or unverifiable (scratch.txt)"

    close = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=lambda **_k: (reason,),
        sweep=_no_sweep,
    )

    assert close.warnings == (f"ITEM-7 at /repo/.worktrees/ITEM-7: {reason}",)
    assert calls[0]["function_id"] == "events.emit"
    payload = calls[0]["payload"]
    assert payload["name"] == terminal_lane_cleanup.LANE_PRESERVED_EVENT_NAME
    assert payload["severity"] == "WARN"
    assert payload["project"] == "yoke"
    assert payload["item_id"] == "7"
    assert payload["context"] == {
        "branch": "ITEM-7",
        "path": "/repo/.worktrees/ITEM-7",
        "target": "main",
        "reason": reason,
    }


def test_refused_preserved_lane_event_is_a_named_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)
    calls: list[dict] = []
    monkeypatch.setattr(
        terminal_lane_cleanup,
        "call_dispatcher",
        _recording_dispatcher(calls, success=False),
    )

    close = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=lambda **_k: ("lane ITEM-7 preserved: branch is not merged into origin/main",),
        sweep=_no_sweep,
    )

    assert len(close.warnings) == 2
    assert close.warnings[1] == "LandedLanePreserved not recorded for ITEM-7: project unknown"


def test_retired_own_lane_records_no_event(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)
    monkeypatch.setattr(
        terminal_lane_cleanup,
        "call_dispatcher",
        lambda **_k: pytest.fail("a retired lane has nothing to record"),
    )

    close = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=lambda **_k: (),
        sweep=_no_sweep,
    )

    assert close.warnings == ()
