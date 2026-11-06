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

from runtime.api.domain.standalone_item_merge_close_out_route_test_support import (
    LANE_SHA as LANE_SHA,
    MERGE_SHA as MERGE_SHA,
    _item as _item,
    _run as _run,
    _wire as _wire,
)


import json

from yoke_core.domain import release_wait_park
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute


def test_a_pending_release_wait_lands_there_and_keeps_the_lane_and_claim(
    monkeypatch,
    capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(stages=("release",)),
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
    assert parked["item_id"] == "ITEM-7"
    assert parked["public_ref"] == "ITEM-7"


def test_a_delivery_already_clear_still_closes_out_and_retires_the_lane(
    monkeypatch,
    capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(stages=("done",)),
    )

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    payloads = dict(calls)
    assert payloads["lifecycle.transition.execute"]["target_status"] == "done"
    assert len(retirements) == 1
    assert cleared == ["ITEM-7"]
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
    monkeypatch,
    capsys,
) -> None:
    """A re-entry got here because a wake delivered a prompt, and that prompt
    cleared the park. Declining without putting it back hands off an owner
    who is awake, still waiting, and no longer declared."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(error="delivery authority unreadable"),
    )
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: True)

    exit_code = _run()

    assert exit_code == 1
    [re_parked] = retained
    assert re_parked["item_id"] == "ITEM-7"
    assert re_parked["public_ref"] == "ITEM-7"
    # The owner keeps the item and the wait; the landed lane is still swept,
    # because nothing downstream of a release wait can retire it later.
    assert [call[1]["landing_recorded"] for call in retirements] == [True]


def test_a_refusal_short_of_the_release_wait_parks_nobody(
    monkeypatch,
    capsys,
) -> None:
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(error="delivery authority unreadable"),
    )
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: False)

    assert _run() == 1
    assert retained == []


def test_a_merge_only_item_walks_every_declared_stage_to_done(
    monkeypatch,
    capsys,
) -> None:
    """A release-bearing pinned graph declares no shortcut to ``done``, so a
    merge whose delivery is already discharged transitions through the
    release wait -- running that stage's own gates -- and asserts the
    done-transition ceremony it has just performed."""
    calls, retirements, cleared, retained = _wire(
        monkeypatch,
        route=CloseOutRoute(
            stages=("release", "done"),
            delivery_discharged=True,
        ),
    )

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    transitions = [
        payload
        for function_id, payload in calls
        if function_id == "lifecycle.transition.execute"
    ]
    assert [
        (payload["source_status"], payload["target_status"]) for payload in transitions
    ] == [("reviewing-implementation", "release"), ("release", "done")]
    assert [payload["done_nonce_verified"] for payload in transitions] == [
        False,
        True,
    ]
    assert len(retirements) == 1
    assert cleared == ["ITEM-7"]
