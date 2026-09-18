"""The merge boundary walks the close-out route its pinned delivery resolves.

Exercises the actual CLI orchestration (``yoke merge item``'s ``run()``),
not just the isolated route resolution already covered in
``test_standalone_item_merge_close_out_route_resolution.py``: an item landing
at its release wait must report that real resulting status and must not run
the ``done``-only lane/claim retirement, a resolved-clear item still gets
both, and a merge-only item whose pinned graph routes through a release wait
transitions through every declared stage on the way.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import release_wait_park
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_close_out_transition as close_out_transition
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def _item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "deployment_flow": "prod-default",
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-7", "path": "/repo/.worktrees/ITEM-7"}],
    }


def _wire(monkeypatch, *, route):
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
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
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, ""),
    )
    monkeypatch.setattr(merge_cli.close_out.terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery, "claim_error", lambda *_a: "",
    )
    calls: list = []

    def dispatch(*, function_id, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        close_out_transition, "close_out_route", lambda *_a, **_k: route,
    )
    retained: list = []

    def record(envelope, **kw):
        retained.append(kw)
        envelope.setdefault("release_wait", {"parked": "yes"})

    monkeypatch.setattr(close_out_transition, "retain_for_delivery", record)
    # retain_if_waiting stays real, so the refusal paths exercise its own
    # release-wait test; only the two writes underneath it are stood in for.
    monkeypatch.setattr(release_wait_park, "retain_for_delivery", record)
    retirements: list = []
    monkeypatch.setattr(
        merge_cli, "record_terminal_lane_close_out",
        lambda *a, **kw: retirements.append((a, kw)),
    )
    cleared: list = []
    monkeypatch.setattr(
        merge_cli.pending, "clear_after_close_out",
        lambda item_id, _item: cleared.append(item_id) or "",
    )
    return calls, retirements, cleared, retained


def _run():
    return merge_cli.run(
        ["ITEM-7", "--result", "landed", "--verification", "suite green"],
    )


def test_a_pending_release_wait_lands_there_and_keeps_the_lane_and_claim(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch, route=CloseOutRoute(stages=("release",)),
    )

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "release"
    payloads = dict(calls)
    assert payloads["lifecycle.transition.execute"]["target_status"] == "release"
    assert payloads["lifecycle.transition.execute"]["done_nonce_verified"] is False
    assert retirements == []
    assert cleared == []
    # The claim is kept AND the session is parked on the wait it just entered:
    # a retention nothing declared is one the stale sweep reclaims.
    [parked] = retained
    assert parked["item_id"] == 7
    assert parked["public_ref"] == "ITEM-7"


def test_a_delivery_already_clear_still_closes_out_and_retires_the_lane(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch, route=CloseOutRoute(stages=("done",)),
    )

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    payloads = dict(calls)
    assert payloads["lifecycle.transition.execute"]["target_status"] == "done"
    assert len(retirements) == 1
    assert cleared == [7]
    assert retained == []


def test_mid_progress_work_stays_at_its_own_status(monkeypatch, capsys) -> None:
    """A still-implementing Blitz slice: not forced to release by stage
    order alone, and not treated as an error either."""
    calls, retirements, cleared, retained = _wire(monkeypatch, route=CloseOutRoute())

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "reviewing-implementation"
    assert calls == []
    assert retirements == []
    assert cleared == []
    # Mid-progress work owns no wait, so it is not parked on one either.
    assert retained == []


def test_a_refused_clearance_re_parks_the_owner_it_leaves_waiting(
    monkeypatch, capsys,
) -> None:
    """A re-entry got here because a wake delivered a prompt, and that prompt
    cleared the park. Declining without putting it back hands off an owner
    who is awake, still waiting, and no longer declared."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch, route=CloseOutRoute(error="delivery authority unreadable"),
    )
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: True)

    exit_code = _run()

    assert exit_code == 1
    [re_parked] = retained
    assert re_parked["item_id"] == 7
    assert re_parked["public_ref"] == "ITEM-7"
    assert retirements == []


def test_a_refusal_short_of_the_release_wait_parks_nobody(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch, route=CloseOutRoute(error="delivery authority unreadable"),
    )
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: False)

    assert _run() == 1
    assert retained == []


def test_a_merge_only_item_walks_every_declared_stage_to_done(
    monkeypatch, capsys,
) -> None:
    """A release-bearing pinned graph declares no shortcut to ``done``, so a
    merge whose delivery is already discharged transitions through the
    release wait -- running that stage's own gates -- and asserts the
    done-transition ceremony it has just performed."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(
            stages=("release", "done"), delivery_discharged=True,
        ),
    )

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    transitions = [
        payload for function_id, payload in calls
        if function_id == "lifecycle.transition.execute"
    ]
    assert [
        (payload["source_status"], payload["target_status"])
        for payload in transitions
    ] == [("reviewing-implementation", "release"), ("release", "done")]
    assert [payload["done_nonce_verified"] for payload in transitions] == [
        False, True,
    ]
    assert len(retirements) == 1
    assert cleared == [7]


def test_a_refused_step_stops_the_walk_and_reports_the_refusal(
    monkeypatch, capsys,
) -> None:
    """The stage in between is a real transition with real gates: when it
    refuses, the close-out reports that refusal rather than carrying on to a
    terminal status the item never legally reached."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(
            stages=("release", "done"), delivery_discharged=True,
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
        merge_cli.close_out.terminal, "call_dispatcher", refuse_release,
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
    assert retirements == []
    assert cleared == []

def test_an_unresolved_delivery_clearance_refuses_rather_than_guesses(
    monkeypatch, capsys,
) -> None:
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
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
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, ""),
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
