"""Re-entering a landing the control-plane observer already recorded.

The queue merges on GitHub whether or not a process is watching, and the
observer records that merge on the item. Re-entering then finds a pull
request the queue has forgotten and a train that has already run, so every
read the full path makes would answer "not admitted" about a merge that
happened. The recorded landing is what lets re-entry skip straight to the
bookkeeping it still owes.
"""

from runtime.api.merge_queue_landing_test_helpers import (
    dispatch_for,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_close_out import QueueCloseOut


LANDED = {"pr_number": "42", "landed_at": "2026-09-03T10:00:00Z"}


def test_a_recorded_landing_closes_out_without_consulting_the_queue(monkeypatch):
    wire_happy_path(monkeypatch)

    def forbidden(*_a, **_kw):
        raise AssertionError("a recorded landing never re-enters the queue")

    monkeypatch.setattr(route_mod, "read_queue_members", forbidden)
    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden)
    monkeypatch.setattr(landing_pr_mod, "find_landable_pull_request", forbidden)
    landed: list[str] = []
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **kw: (
            landed.append(kw["pr_num"])
            or QueueCloseOut(
                merge_sha="n" * 40,
                touched_files=("a.py",),
            )
        ),
    )

    outcome = land(dispatch=dispatch_for({"YOK-200": {}}, merge_queue=LANDED))

    assert outcome.ok
    assert outcome.already_merged
    assert outcome.pr_num == "42"
    assert landed == ["42"]


def test_a_recorded_pull_request_that_has_not_landed_takes_the_full_path(monkeypatch):
    """Arming a pull request records it, which is not evidence it merged."""
    wire_happy_path(monkeypatch)

    outcome = land(
        dispatch=dispatch_for({"YOK-200": {}}, merge_queue={"pr_number": "42"}),
    )

    assert outcome.ok
    assert outcome.pr_num == "42"
