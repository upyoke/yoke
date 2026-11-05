# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge as sim

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import standalone_item_merge_close_out_report as report

from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)

from yoke_core.domain import standalone_item_merge_evidence as merge_evidence

from yoke_core.domain import standalone_item_merge_git as git

from yoke_core.domain import standalone_item_merge_verify as verify

from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

LANE_SHA = "1" * 40

MERGE_SHA = "2" * 40

SESSION = "session-under-test"


def _response(result=None, *, success=True, message=""):
    error = None if success else SimpleNamespace(message=message)
    return SimpleNamespace(success=success, result=result or {}, error=error)


def _outcome_block(captured_err: str) -> list[str]:
    prefix = f"{report.LINE_PREFIX} "
    return [
        line[len(prefix) :]
        for line in captured_err.splitlines()
        if line.startswith(prefix)
    ]


def _item(status: str = "reviewing-implementation") -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": status,
        "workflow": {"id": "dash", "terminal_stage_ids": ["done"]},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/.worktrees/ITEM-1", "branch": "ITEM-1"}],
    }


def _run_close_out(
    monkeypatch, *, holder=None, argv=None, holder_dispatch=None
) -> None:
    """Drive a complete merge whose close-out reaches the terminal status."""
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: (LANE_SHA, ""))
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda _item_id: None)
    monkeypatch.setattr(git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        merge_cli, "record_terminal_lane_close_out", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        close_out_transition,
        "close_out_route",
        lambda *_a, postpone_terminal=False, **_k: (
            CloseOutRoute(stages=("release",))
            if postpone_terminal
            else CloseOutRoute(stages=("done",))
        ),
    )

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == report.HOLDER_FUNCTION:
            if holder_dispatch is not None:
                return holder_dispatch(function_id=function_id, target=target)
            return _response({"holder": holder})
        return _response()

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery, "claim_error", lambda *_a: ""
    )
    exit_code = merge_cli.run(
        argv
        or [
            "ITEM-1",
            "--result",
            "landed",
            "--verification",
            "green",
            "--session-id",
            SESSION,
        ]
    )
    assert exit_code == 0
