"""Cancelling an item retires its lanes, exactly as closing it out does.

Cancel is terminal: the control plane releases the item's lane rows in the
same transaction, so the directory and branch on this machine have no owner
left. Only the transition command used to retire them, which is why
cancelled items were the ones found still holding a worktree.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.commands import _helpers
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import terminal_lane_cleanup

ITEM = {
    "id": 7,
    "public_ref": "ITEM-1",
    "status": "implementing",
    "workflow": {"id": "dash", "terminal_stage_ids": ["done", "cancelled"]},
    "worktrees": [{"branch": "ITEM-1", "path": "/repo/.worktrees/ITEM-1"}],
}


@pytest.fixture()
def retirements(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        _helpers, "build_actor", lambda **_kw: SimpleNamespace(session_id="session-1")
    )
    monkeypatch.setattr(_helpers, "emit_response", lambda *_a, **_kw: 0)
    monkeypatch.setattr(
        terminal_lane_cleanup,
        "cleanup_terminal_item_lanes",
        lambda item, **kwargs: calls.append({"item": item, **kwargs})
        or terminal_lane_cleanup.TerminalLaneCloseOut(),
    )
    return calls


def _dispatch(monkeypatch, result: dict) -> None:
    def dispatch(*, function_id, **_kwargs):
        if function_id == "items.detail.get":
            return SimpleNamespace(success=True, result={"item": ITEM}, error=None)
        return SimpleNamespace(success=True, result=result, error=None)

    monkeypatch.setattr(_helpers, "call_dispatcher", dispatch)


def _run(function_id: str, payload: dict) -> int:
    return _helpers.dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="item", item_id=7),
        payload=payload,
        session_id="session-1",
        json_mode=True,
    )


def test_cancel_retires_the_lanes_it_just_released(monkeypatch, retirements):
    """The cancel payload names no status, so the result is read instead."""
    _dispatch(monkeypatch, {"item_id": 7, "status": "cancelled"})

    assert _run("items.cancel.run", {"reason": "superseded"}) == 0
    assert retirements[0]["target_status"] == "cancelled"
    assert retirements[0]["item"]["worktrees"][0]["branch"] == "ITEM-1"


def test_a_transition_retires_against_the_status_it_reached(
    monkeypatch, retirements
):
    """The reached status is the transition's own answer, not the request."""
    _dispatch(monkeypatch, {"item_id": 7, "from_status": "implementing", "to_status": "done"})

    assert _run("lifecycle.transition.execute", {"target_status": "done"}) == 0
    assert retirements[0]["target_status"] == "done"


def test_a_non_terminal_capable_call_reads_no_item_detail(monkeypatch, retirements):
    """Ordinary calls pay for neither the extra read nor the retirement."""
    _dispatch(monkeypatch, {"ok": True})

    assert _run("items.progress_log.append", {"headline": "note"}) == 0
    assert retirements == []
