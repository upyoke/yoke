"""A queue landing converges on whatever the pull request actually did.

The queue merges on GitHub whether or not the process watching it survives,
and it clears merge-when-ready both when it merges a pull request and when it
drops one. Every case here is a landing that already happened, or is about to,
being read by a process that must not mistake it for a failure — and the one
genuine stall, which has to stay diagnosable.
"""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    land,
    landing_record,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_record_state as record_state
from yoke_core.domain import merge_queue_route as route_mod


def test_stalled_landing_names_every_fact_it_observed(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    narrative = (
        "pull request 42: merged=false, state=open, "
        "merge-when-ready=cleared, queue-entry=neither, "
        "mergeStateStatus=CLEAN, failed-required-checks=none"
    )
    outcome = land(
        landing_records=[landing_record(record_state.STALLED, narrative=narrative)]
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "no longer driving pull request 42" in outcome.error
    assert "state=open" in outcome.error
    assert "merge-when-ready=cleared" in outcome.error
    assert "queue-entry=neither" in outcome.error
    assert "mergeStateStatus=CLEAN" in outcome.error


def test_cleared_arming_while_the_train_validates_keeps_polling(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    outcome = land(
        landing_records=[
            landing_record(
                record_state.PENDING,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "merge-when-ready=consumed, queue-entry=enqueued"
                ),
            ),
            landing_record(),
        ]
    )
    assert outcome.ok
    assert outcome.exit_code == 0


def test_green_train_with_cleared_slot_still_converges(monkeypatch):
    """GitHub drops the slot before merged=true; that is not a stall."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    outcome = land(
        landing_records=[
            landing_record(
                record_state.PENDING,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "merge-when-ready=consumed, queue-entry=enqueued"
                ),
            ),
            landing_record(),
        ]
    )
    assert outcome.ok
    assert outcome.exit_code == 0


def test_server_recorded_merge_converges_without_a_client_read(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    assert land().ok


def test_unreadable_server_queue_record_never_classifies_a_stall(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    outcome = land(
        landing_records=[
            landing_record(
                record_state.PENDING,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=unreadable (queue read failed)"
                ),
            ),
            landing_record(),
        ]
    )
    assert outcome.ok


def test_closed_unmerged_is_terminal(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    outcome = land(
        landing_records=[
            landing_record(
                record_state.CLOSED_UNMERGED,
                narrative=(
                    "pull request 42: merged=false, state=closed, "
                    "merge-when-ready=cleared, queue-entry=neither"
                ),
            )
        ]
    )
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "closed without merging" in outcome.error
    assert "state=closed" in outcome.error


def test_dirty_pull_request_names_rebase_and_does_not_keep_waiting(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    announced: list[str] = []
    outcome = land(
        emit=announced.append,
        landing_records=[
            landing_record(
                record_state.CONFLICTED,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=neither, mergeStateStatus=DIRTY"
                ),
            )
        ],
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "merge conflicts" in outcome.error
    assert "rebase the lane onto main" in outcome.error
    assert "re-run the verification gate" in outcome.error
    assert "yoke merge item" in outcome.error
    assert "Re-running the landing is safe" not in outcome.error
    assert "mergeStateStatus=DIRTY" in outcome.error
    assert any("mergeStateStatus=DIRTY" in line for line in announced)


def test_wait_announces_a_recorded_merge_state_status_transition(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
    )
    announced: list[str] = []
    outcome = land(
        emit=announced.append,
        landing_records=[
            landing_record(
                record_state.PENDING,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=armed_not_enqueued, "
                    "mergeStateStatus=BLOCKED"
                ),
            ),
            landing_record(
                record_state.CONFLICTED,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=neither, mergeStateStatus=DIRTY"
                ),
            ),
        ],
    )
    assert not outcome.ok
    assert any("mergeStateStatus=BLOCKED" in line for line in announced)
    assert any("mergeStateStatus=DIRTY" in line for line in announced)
    assert announced[0] != announced[-1]
