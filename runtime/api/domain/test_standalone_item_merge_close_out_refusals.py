"""Close-out refusals preserve the real stage and report missing authority."""

import json
from types import SimpleNamespace
from pathlib import Path

from runtime.api.domain.test_standalone_item_merge_close_out_route import (
    _wire,
    _run,
    _item,
    LANE_SHA,
    MERGE_SHA,
)
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute


def test_a_refused_step_stops_the_walk_and_reports_the_refusal(
    monkeypatch,
    capsys,
) -> None:
    """The stage in between is a real transition with real gates: when it
    refuses, the close-out reports that refusal rather than carrying on to a
    terminal status the item never legally reached."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(
            stages=("release", "done"),
            delivery_discharged=True,
        ),
    )

    def refuse_release(*, function_id, payload=None, **_kw):
        calls.append((function_id, payload))
        if payload and payload.get("target_status") == "release":
            return SimpleNamespace(
                success=False,
                result={},
                error=SimpleNamespace(message="blocking QA requirement unsatisfied"),
            )
        raise AssertionError("the walk must stop at the refused stage")

    monkeypatch.setattr(
        merge_cli.close_out.terminal,
        "call_dispatcher",
        refuse_release,
    )
    monkeypatch.setattr(
        merge_cli.evidence,
        "recorded_landing_envelope",
        lambda *_a, **_k: None,
    )

    exit_code = _run()

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert envelope["ok"] is False
    assert "blocking QA requirement unsatisfied" in envelope["error"]
    # The landing still authorizes retiring the lane. Lane release is
    # otherwise reachable only from the review stage, so leaving it here
    # strands the item at its release wait holding a lane nothing can
    # retire — and each lane still proves itself merged before anything
    # is removed, so unshipped work is preserved regardless.
    assert [call[1]["landing_recorded"] for call in retirements] == [True]
    assert cleared == []


def test_an_unresolved_delivery_clearance_refuses_rather_than_guesses(
    monkeypatch,
    capsys,
) -> None:
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
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
            touched_files=("feature.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(merge_cli.evidence, "record", lambda **_k: "")
    monkeypatch.setattr(sim, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli.release_flow,
        "continue_prepared_release",
        lambda **_k: (None, ""),
    )
    monkeypatch.setattr(
        close_out_transition,
        "close_out_route",
        lambda *_a, **_k: CloseOutRoute(
            error="the pinned workflow definition could not be read",
        ),
    )
    monkeypatch.setattr(
        merge_cli.close_out.terminal,
        "call_dispatcher",
        lambda **_k: (_ for _ in ()).throw(
            AssertionError("an unresolved clearance must not attempt a transition")
        ),
    )

    exit_code = _run()

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert envelope["ok"] is False
    assert "delivery clearance could not be resolved" in envelope["error"]
