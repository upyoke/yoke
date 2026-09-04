"""Cap-overruled promised-work must name unfinished work and recovery at WARN."""

from __future__ import annotations

from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain import turn_end_unfinished_work as unfinished
from yoke_core.domain.sessions_render_end_chain_pending import ChainPendingState


class _Conn:
    def close(self) -> None:
        return None


def _state() -> ChainPendingState:
    return ChainPendingState(
        pending=False,
        step=0,
        max_chain_steps=3,
        chainable=False,
        handler_outcome=None,
        action=None,
        item_id=None,
    )


def _patch_emit(monkeypatch) -> list[dict]:
    emitted: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.chain_pending_state",
        lambda conn, sid: _state(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.last_released_at",
        lambda conn, sid: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.scheduler_events.emit_chain_end_deferred",
        lambda **kwargs: emitted.append(kwargs),
    )
    return emitted


def test_cap_names_close_out_and_warns(monkeypatch) -> None:
    emitted = _patch_emit(monkeypatch)
    claim = {
        "item_id": 2652,
        "status": "reviewing-implementation",
        "merged_at": "2026-08-28T21:24:11Z",
        "merge_queue_landed_at": None,
    }
    gate._emit_deferred(
        conn=_Conn(),
        session_id="sess-1",
        item_id=2652,
        reason=gate.REASON_CAP_REACHED,
        cap_reached=True,
        claim=claim,
    )
    payload = emitted[0]
    assert payload["reason"] == gate.REASON_CAP_REACHED
    assert payload["cap_reached"] is True
    assert payload["severity"] == "WARN"
    assert payload["unfinished_work"] == unfinished.UNFINISHED_CLOSE_OUT
    assert payload["item_status"] == "reviewing-implementation"
    assert "status is not the landing signal" in payload["recovery"]
    assert "yoke merge item 2652" in payload["recovery"]


def test_cap_without_landing_stamp_names_claimed_item() -> None:
    claim = {"item_id": 9, "status": "implementing"}
    assert unfinished.unfinished_work_name(claim) == unfinished.UNFINISHED_CLAIMED_ITEM
    assert unfinished.recovery_for(claim) == gate.DIRECTIVE
