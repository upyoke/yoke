"""Close-out names each step so a killed capture shows where it stopped."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def test_close_out_emits_a_phase_marker_for_each_step(monkeypatch, capsys):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash", "terminal_stage_ids": ["done"]},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/.worktrees/ITEM-1", "branch": "ITEM-1"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        verify, "qa_preflight",
        lambda *_a, **_k: (LANE_SHA, ""),
    )
    monkeypatch.setattr(
        verify, "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True, exit_code=0, already_merged=False,
            commit_sha=LANE_SHA, merge_sha=MERGE_SHA,
            touched_files=("a.py",), pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda _item_id: None)
    monkeypatch.setattr(git, "is_landed", lambda *_a: True)

    def dispatch(*, function_id, target, payload=None, **_kw):
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery, "claim_error", lambda *_a: ""
    )

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "green"],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    for step in (
        "recording evidence",
        "syncing GitHub",
        "terminal transition",
        "lane cleanup",
    ):
        assert f"[phase:close-out] {step}" in err
