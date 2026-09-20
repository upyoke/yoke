"""A close-out whose delivery has not happened holds the item at its wait.

The route decision itself is covered in
``test_close_out_route_delivery_readability.py``; this is what the terminal
transition does with it. The item is already standing at its release wait,
so there is nothing to transition: walking to the terminal stage instead
spent the transition on a ceremony only a deploy can perform, and the owner
got "missing done-transition ceremony nonce" — a refusal naming neither the
delivery it was waiting on nor anything it could do about it.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import release_wait_park
from yoke_core.domain import standalone_item_merge_close_out_transition as terminal
from yoke_core.domain import standalone_item_merge_close_out_report as report
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

PENDING = (
    "its delivery through flow 'production-release' has not happened yet: the "
    "selected flow's latest run is at status 'executing' (deployment run "
    "run-20260919-020 is at status executing). Execute or retry deployment "
    "run run-20260919-020."
)


def _item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "release",
        "workflow": {"id": "dash"},
        "deployment_flow": "production-release",
        "project": {"slug": "acme"},
    }


def _run(monkeypatch, *, route: CloseOutRoute) -> tuple[dict, list, list]:
    monkeypatch.setattr(terminal, "close_out_route", lambda *_a, **_k: route)
    monkeypatch.setattr(release_wait_park, "at_release_wait", lambda *_a: True)
    parked: list = []
    monkeypatch.setattr(
        release_wait_park,
        "retain_for_delivery",
        lambda envelope, **kw: (
            parked.append(kw), envelope.setdefault("release_wait", {"parked": "yes"}),
        ),
    )
    transitions: list = []
    close_out = SimpleNamespace(
        transition_to_done=lambda **kw: (
            transitions.append(kw), ("done", ""),
        )[1],
    )
    retirements: list = []
    envelope: dict = {"warnings": [], "public_ref": "ITEM-7", "item_id": 7}
    exit_code = terminal.run_terminal_transition(
        item=_item(),
        item_id=7,
        public_ref="ITEM-7",
        branch="ITEM-7",
        target="main",
        status="release",
        close_lane=LandedLane(
            branch="ITEM-7", target="main", commit_sha="1" * 40, merge_sha="2" * 40,
        ),
        session_id="session-1",
        repo_root="",
        envelope=envelope,
        announce=lambda *_a, **_k: None,
        close_out=close_out,
        evidence=SimpleNamespace(CLOSED_OUT_STATUS="done"),
        pending=SimpleNamespace(clear_after_close_out=lambda *_a: ""),
        record_terminal_lane_close_out=lambda *a, **kw: retirements.append(kw),
    )
    assert exit_code is None
    return envelope, transitions, parked


def test_an_undelivered_close_out_stays_put_and_names_its_delivery(
    monkeypatch,
) -> None:
    envelope, transitions, parked = _run(
        monkeypatch, route=CloseOutRoute(delivery_pending=PENDING),
    )

    # No transition attempted, so no ceremony to be missing.
    assert transitions == []
    assert envelope["status"] == "release"
    assert envelope["delivery_pending"] == PENDING
    assert "run-20260919-020" in envelope["delivery_pending"]
    # The wake that re-enters this command cleared the owner's park, so a
    # close-out that stops short of done has to put it back.
    assert [entry["item_id"] for entry in parked] == [7]


def test_the_wait_it_is_holding_is_what_the_owner_is_told(monkeypatch) -> None:
    """The reason belongs where the owner reads, not only in the JSON."""
    envelope, _transitions, _parked = _run(
        monkeypatch, route=CloseOutRoute(delivery_pending=PENDING),
    )
    kind, blocker = report.final_outcome(
        envelope, source_status="release", skip_status=False,
    )

    assert kind == report.AWAITING_DELIVERY
    lines = report.outcome_lines(envelope, kind=kind, blocker=blocker)
    rendered = "\n".join(lines)
    assert "waiting on:" in rendered
    assert "run-20260919-020" in rendered
    assert "nonce" not in rendered
    assert "do not release" in rendered


def test_a_discharged_delivery_still_walks_to_the_terminal_stage(
    monkeypatch,
) -> None:
    """The unchanged path: delivery happened, so the close-out finishes."""
    envelope, transitions, parked = _run(
        monkeypatch,
        route=CloseOutRoute(stages=("done",), delivery_discharged=True),
    )

    assert [entry["stages"] for entry in transitions] == [("done",)]
    assert transitions[0]["delivery_discharged"] is True
    assert envelope["status"] == "done"
    assert "delivery_pending" not in envelope
    assert parked == []
