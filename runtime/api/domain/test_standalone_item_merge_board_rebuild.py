"""Board refresh ownership at standalone merge and lifecycle close-out."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.api.backlog_github_sync_test_helpers import make_db
from runtime.api.conftest import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog
from yoke_core.domain import backlog_github_item_create
from yoke_core.domain import backlog_github_sync
from yoke_core.domain import backlog_rendering
from yoke_core.domain import events
from yoke_core.domain import rebuild_board
from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.board_rebuild_failure import (
    BOARD_REBUILD_FAILED_EVENT_NAME,
    RECOVERY_COMMAND,
)
from yoke_core.domain.handlers import lifecycle_transition


LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def _wire_landed_close_out(monkeypatch, item: dict) -> None:
    outcome = merge_boundary.StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=False,
        commit_sha=LANE_SHA,
        merge_sha=MERGE_SHA,
        touched_files=("changed.py",),
        pushed=True,
    )
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        verify,
        "verify_and_land",
        lambda *_a, **_kw: (outcome, ""),
    )
    monkeypatch.setattr(
        merge_cli.close_out,
        "record_execution_evidence",
        lambda **_kw: ("", ""),
    )

    def transition(**_kwargs) -> str:
        item["status"] = "done"
        return ""

    monkeypatch.setattr(merge_cli.close_out, "transition_to_done", transition)
    monkeypatch.setattr(
        merge_cli,
        "cleanup_terminal_item_lanes",
        lambda *_a, **_kw: SimpleNamespace(warnings=(), sweep={}),
    )
    monkeypatch.setattr(
        merge_cli.pending,
        "clear_after_close_out",
        lambda *_a: "",
    )


def test_sync_disabled_close_out_skips_mirror_and_rebuilds_board(monkeypatch):
    db = make_db()
    try:
        db.execute(
            "UPDATE projects SET github_sync_mode='disabled' "
            "WHERE slug='externalwebapp'"
        )
        db.commit()
        insert_item(
            db,
            id=71,
            project="externalwebapp",
            workflow_id="dash",
            status="reviewing-implementation",
        )
        mirror_calls: list[int] = []
        monkeypatch.setattr(
            backlog_github_item_create.github_rest,
            "create_issue",
            lambda **_kw: mirror_calls.append(71),
        )

        def disabled_sync(item_id: int) -> None:
            assert backlog_github_sync.sync_item(item_id, conn=db) == 0

        monkeypatch.setattr(merge_boundary, "sync_item_to_github", disabled_sync)
        board_calls: list[bool] = []
        monkeypatch.setattr(
            backlog,
            "_maybe_rebuild_board",
            lambda requested: board_calls.append(requested) or "",
        )
        item = {
            "id": 71,
            "public_ref": "EXT-71",
            "status": "reviewing-implementation",
            "workflow": {"id": "dash"},
            "project": {"slug": "externalwebapp"},
            "worktrees": [{"path": "/repo/lane", "branch": "EXT-71"}],
        }
        _wire_landed_close_out(monkeypatch, item)

        result = merge_cli.run(
            ["EXT-71", "--result", "landed", "--verification", "green"]
        )

        assert result == 0
        assert mirror_calls == []
        assert board_calls == [True]
        assert item["status"] == "done"
    finally:
        db.close()


def test_rebuild_failure_leaves_lifecycle_item_done(monkeypatch):
    state = {"status": "reviewing-implementation"}
    monkeypatch.setattr(
        lifecycle_transition,
        "_read_current_status",
        lambda _item_id: (state["status"], "ITEM-7"),
    )
    monkeypatch.setattr(
        lifecycle_transition,
        "_frozen_blocked",
        lambda *_a: None,
    )

    def execute_update(**kwargs) -> dict:
        assert kwargs["rebuild_board"] is False
        state["status"] = str(kwargs["value"])
        return {"success": True}

    monkeypatch.setattr(backlog, "execute_update", execute_update)
    monkeypatch.setattr(
        backlog_rendering,
        "_yoke_root",
        lambda: Path("/repo/.yoke"),
    )
    monkeypatch.delenv("YOKE_DB", raising=False)
    monkeypatch.setattr(
        rebuild_board,
        "rebuild",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("render exploded")),
    )
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        events,
        "emit_event",
        lambda name, **kwargs: emitted.append((name, kwargs)),
    )
    request = FunctionCallRequest(
        function="lifecycle.transition.execute",
        actor=ActorContext(actor_id="2", session_id="session-A"),
        target=TargetRef(kind="item", item_id=7),
        payload={
            "source_status": "reviewing-implementation",
            "target_status": "done",
            "reason": "merge landed",
        },
    )

    outcome = lifecycle_transition.handle_transition(request)

    assert outcome.primary_success is True
    assert state["status"] == "done"
    assert "[board-rebuild-failed] RuntimeError: render exploded" in str(
        outcome.result_payload["log"]
    )
    assert f"retry with `{RECOVERY_COMMAND}`" in outcome.result_payload["log"]
    assert [name for name, _kwargs in emitted] == [BOARD_REBUILD_FAILED_EVENT_NAME]
    assert emitted[0][1]["context"]["recovery_command"] == RECOVERY_COMMAND
