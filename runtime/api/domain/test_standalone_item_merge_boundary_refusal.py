"""A refused close-out keeps the lane its retry may still need.

A lifecycle gate refusal is cleared by re-running the same close-out, and a
boundary refusal's recovery may read the lane. Sweeping it after the refusal
removed the only recovery, so a gate refusal leaves the lane in place while
any other refusal still retires a landed lane as before.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import release_wait_park
from yoke_core.domain import standalone_item_merge_close_out_transition as terminal
from yoke_core.domain import standalone_item_merge_terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute
from yoke_core.domain.standalone_item_merge_terminal import (
    GATE_REFUSAL_CODE,
    TransitionRefusal,
)


def _run(monkeypatch, refusal: str) -> tuple[int, dict, list]:
    monkeypatch.setattr(
        terminal,
        "close_out_route",
        lambda *_a, **_k: CloseOutRoute(stages=("release",)),
    )
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: False)
    swept: list = []
    envelope: dict = {"warnings": [], "public_ref": "ITEM-7", "item_id": 7}
    exit_code = terminal.run_terminal_transition(
        item={"id": 7, "public_ref": "ITEM-7", "status": "implemented"},
        item_id=7,
        public_ref="ITEM-7",
        branch="ITEM-7",
        target="main",
        status="implemented",
        close_lane=LandedLane(
            branch="ITEM-7",
            target="main",
            commit_sha="1" * 40,
            merge_sha="2" * 40,
        ),
        session_id="session-1",
        repo_root="",
        envelope=envelope,
        announce=lambda *_a, **_k: None,
        close_out=SimpleNamespace(transition_to_done=lambda **_kw: ("", refusal)),
        evidence=SimpleNamespace(
            CLOSED_OUT_STATUS="done",
            recorded_landing_envelope=lambda *_a, **_k: None,
        ),
        pending=SimpleNamespace(clear_after_close_out=lambda *_a: ""),
        record_terminal_lane_close_out=lambda *a, **kw: swept.append(kw),
    )
    return exit_code, envelope, swept


def test_boundary_gate_refusal_keeps_the_lane(monkeypatch) -> None:
    refusal = TransitionRefusal(
        "Path-claim boundary check blocked transition to 'release'",
        GATE_REFUSAL_CODE,
    )
    exit_code, envelope, swept = _run(monkeypatch, refusal)

    assert exit_code == 1
    assert envelope["ok"] is False
    assert "boundary check blocked" in envelope["error"]
    assert swept == []
    assert any("lane kept for the retry" in w for w in envelope["warnings"])


def test_non_gate_refusal_still_sweeps_the_landed_lane(monkeypatch) -> None:
    refusal = TransitionRefusal("transport refused", "service_unavailable")
    exit_code, envelope, swept = _run(monkeypatch, refusal)

    assert exit_code == 1
    assert [entry.get("landing_recorded") for entry in swept] == [True]


def test_execute_keeps_the_relay_code_beside_the_message(monkeypatch) -> None:
    response = SimpleNamespace(
        success=False,
        error=SimpleNamespace(code=GATE_REFUSAL_CODE, message="gate unmet"),
    )
    monkeypatch.setattr(
        standalone_item_merge_terminal, "call_dispatcher", lambda **_kw: response
    )
    refusal = standalone_item_merge_terminal._execute("YOK-7", "implemented", "release")

    assert refusal == "gate unmet"
    assert refusal.code == GATE_REFUSAL_CODE
