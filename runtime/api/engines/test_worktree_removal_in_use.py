"""A lane another program holds is deferred, not reported as a raw WinError.

Windows refuses to rename a folder a shell stands in (WinError 5) or a program
holds a file in (WinError 32). The merge still closes the item, names the lane
as deferred cleanup with its recovery, and a held moment is outlasted by the
shared sharing-violation retry. The rename is faked only for the lane folder;
every git fact is real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.engines._merge_landed_lane_test_helpers import (
    BRANCH,
    _land_on_main,
    _run_git,
)
from yoke_contracts import filesystem_safety
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_close_out_report as report
from yoke_core.engines import terminal_lane_cleanup as terminal
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.worktree_removal import remove_worktree

REF = "ITEM-1"
DEFERRED = "lane cleanup deferred"


def _hold_lane(monkeypatch, lane: Path, winerror: int, *, times: int | None = None):
    """Refuse renaming ``lane`` the way Windows does while a program holds it."""
    original = Path.rename
    refusals = {"left": times}

    def rename(self, target):
        if Path(self) == lane and refusals["left"] != 0:
            if refusals["left"] is not None:
                refusals["left"] -= 1
            exc = PermissionError(13, "Access is denied")
            exc.winerror = winerror
            raise exc
        return original(self, target)

    monkeypatch.setattr(Path, "rename", rename)


def _done_item(landed_lane, monkeypatch) -> dict:
    item = {
        "status": "done", "public_ref": REF, "project": {"id": 1},
        "workflow": {"terminal_stage_ids": ["done"]},
        "worktrees": [
            {"branch": BRANCH, "path": str(landed_lane.worktree), "status": "released"}
        ],
    }
    monkeypatch.setattr(terminal, "checkout_for_project_id", lambda _id: landed_lane.repo)
    return item


@pytest.mark.parametrize("winerror", [5, 32])
def test_held_lane_is_in_use_and_the_merge_closes_with_cleanup_deferred(
    landed_lane, monkeypatch, capsys, winerror,
):
    _land_on_main(landed_lane.repo)
    _hold_lane(monkeypatch, landed_lane.worktree, winerror)

    removal = remove_worktree(landed_lane.repo, landed_lane.worktree)
    assert removal.in_use is True
    assert not removal.removed

    item = _done_item(landed_lane, monkeypatch)
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "claim released")
    monkeypatch.setattr(merge_cli.evidence, "recorded", lambda _ref: {})
    assert merge_cli.run(["ITEM-1"]) == 0
    stderr = capsys.readouterr().err
    assert f"{REF} already closed" in stderr
    (warning,) = [line for line in stderr.splitlines() if DEFERRED in line]
    assert "warning:" in warning
    assert f"merged; {DEFERRED}: {landed_lane.worktree} in use by another program" in warning
    assert "relay's lane sweep (every 15 minutes)" in warning
    assert f"rerun `yoke merge item {REF}`" in warning
    assert "WinError" not in stderr and "rename refused" not in stderr
    assert landed_lane.worktree.is_dir()

    # The run that closes the item reports the same deferral under "closed".
    envelope = {"status": "done", "public_ref": REF}
    terminal.record_terminal_lane_close_out(item, envelope, target_status="done")
    kind, blocker = report.final_outcome(
        envelope, source_status="release", skip_status=False
    )
    lines = report.outcome_lines(envelope, kind=kind, blocker=blocker)
    assert lines[0] == f"{REF} closed: done"
    assert any(line.strip().startswith("warning:") and DEFERRED in line for line in lines)


def test_a_rename_held_only_for_a_moment_removes_the_lane_in_the_same_merge(
    landed_lane, monkeypatch,
):
    _land_on_main(landed_lane.repo)
    monkeypatch.setattr(filesystem_safety, "_RETRY_SHARING_VIOLATIONS", True)
    _hold_lane(monkeypatch, landed_lane.worktree, 5, times=1)

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        item_id=REF, run_git=_run_git, emit=lambda *_a, **_kw: None,
    )
    # Only the fake item's lane-row note may remain; the lane itself is gone.
    assert not [note for note in preserved if "preserved" in note or DEFERRED in note]
    assert not landed_lane.worktree.exists()


def test_a_non_windows_permission_refusal_is_named_not_deferred(
    landed_lane, monkeypatch,
):
    _land_on_main(landed_lane.repo)
    original = Path.rename

    def refuse(self, target):
        if Path(self) == landed_lane.worktree:
            raise PermissionError(13, "Permission denied")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", refuse)
    removal = remove_worktree(landed_lane.repo, landed_lane.worktree)
    assert removal.in_use is False
    assert "worktree rename refused" in removal.reason
