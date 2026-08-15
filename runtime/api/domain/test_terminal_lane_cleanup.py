"""Terminal close-out owns physical lane retirement for every outcome."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import terminal_lane_cleanup
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome


LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def _item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash", "terminal_stage_ids": ["done", "cancelled"]},
        "project": {"id": 1, "slug": "yoke", "default_branch": "main"},
        "claim": {"session_id": "session-1"},
        "worktrees": [{"branch": "ITEM-7", "path": "/repo/.worktrees/ITEM-7"}],
    }


def _wire_close_out(monkeypatch, *, already: bool, cleanup_result=()):
    item = _item()
    timeline: list[str] = []
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    monkeypatch.setattr(merge_cli, "qa_preflight", lambda *_a, **_k: (LANE_SHA, ""))
    monkeypatch.setattr(
        merge_cli,
        "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=already,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=(),
            pushed=True,
        ),
    )
    monkeypatch.setattr(merge_cli.evidence, "record", lambda **_k: "")
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli,
        "_transition_to_done",
        lambda *_a: timeline.append("done") or "",
    )
    monkeypatch.setattr(
        merge_cli,
        "cleanup_terminal_item_lanes",
        lambda *_a, **_k: timeline.append("cleanup") or cleanup_result,
    )
    return timeline


def test_verified_no_change_close_out_removes_lane_after_done(monkeypatch):
    timeline = _wire_close_out(monkeypatch, already=False)

    result = merge_cli.run(
        [
            "ITEM-7",
            "--result",
            "no change",
            "--verification",
            "green",
            "--no-changes",
            "--session-id",
            "session-1",
            "--json",
        ]
    )

    assert result == 0
    assert timeline == ["done", "cleanup"]


def test_recovered_landing_removes_lane_after_done(monkeypatch):
    timeline = _wire_close_out(monkeypatch, already=True)

    result = merge_cli.run(
        [
            "ITEM-7",
            "--result",
            "recovered",
            "--verification",
            "green",
            "--session-id",
            "session-1",
            "--json",
        ]
    )

    assert result == 0
    assert timeline == ["done", "cleanup"]


def test_cleanup_refusal_is_reported_without_blocking_done(
    monkeypatch,
    capsys,
):
    _wire_close_out(
        monkeypatch,
        already=False,
        cleanup_result=("ITEM-7: dirty worktree preserved",),
    )

    result = merge_cli.run(
        [
            "ITEM-7",
            "--result",
            "landed",
            "--verification",
            "green",
            "--session-id",
            "session-1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["status"] == "done"
    assert "dirty worktree preserved" in payload["warnings"][0]


def test_close_out_drops_released_claim_before_lane_cleanup(monkeypatch):
    seen: dict = {}
    _wire_close_out(monkeypatch, already=False)
    monkeypatch.setattr(
        merge_cli,
        "cleanup_terminal_item_lanes",
        lambda payload, **_k: seen.update(claim=payload.get("claim")) or (),
    )

    result = merge_cli.run(
        [
            "ITEM-7",
            "--result",
            "landed",
            "--verification",
            "green",
            "--session-id",
            "session-1",
            "--json",
        ]
    )

    assert result == 0
    assert seen["claim"] is None


def test_closing_session_claim_does_not_block_lane_cleanup(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)

    def prune(**kwargs):
        calls.append(kwargs)
        return ()

    warnings = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=prune,
    )

    assert calls[0]["authority_block"] == ""
    assert warnings == ()


def test_ambient_closing_session_does_not_block_when_flag_empty(
    monkeypatch, tmp_path
):
    calls: list[dict] = []
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)
    monkeypatch.setattr(
        terminal_lane_cleanup, "resolve_ambient_session_id", lambda: "session-1"
    )

    def prune(**kwargs):
        calls.append(kwargs)
        return ()

    warnings = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="",
        repo_root=tmp_path,
        prune=prune,
    )

    assert calls[0]["authority_block"] == ""
    assert warnings == ()


def test_foreign_live_claim_is_passed_to_shared_safety_predicate(
    monkeypatch,
    tmp_path,
):
    item = _item()
    item["claim"] = {"session_id": "other-session"}
    calls: list[dict] = []
    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)

    def prune(**kwargs):
        calls.append(kwargs)
        return (f"lane preserved: {kwargs['authority_block']}",)

    warnings = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        item,
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=prune,
    )

    assert calls[0]["authority_block"] == (
        "live work claim belongs to session other-session"
    )
    assert "other-session" in warnings[0]


def test_unexpected_cleanup_error_is_advisory_after_terminal_state(
    monkeypatch, tmp_path
):
    def prune(**_kwargs):
        raise RuntimeError("cleanup transport unavailable")

    monkeypatch.setattr(terminal_lane_cleanup.git, "branch_exists", lambda *_a: True)
    warnings = terminal_lane_cleanup.cleanup_terminal_item_lanes(
        _item(),
        target_status="done",
        session_id="session-1",
        repo_root=tmp_path,
        prune=prune,
    )

    assert "unexpected refusal" in warnings[0]
    assert "cleanup transport unavailable" in warnings[0]
