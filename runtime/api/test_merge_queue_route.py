"""Queue-routed landing orchestration: admission, entry, poll, close-out."""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    HELD_BY_THIS_SESSION,
    MERGED,
    UNARMED,
    dispatch_for,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_failed_train as failed_train_mod
from yoke_core.domain import merge_queue_landing_timeout as timeout_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import session_liveness_pump as liveness_mod
from yoke_core.domain.merge_queue_landing_verdict import LandingCheck
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_pr_queue import QueueMember, TrainRun


class StubPump:
    """A liveness pump that records rather than touching a live session."""

    def __init__(self):
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        return True

    def wait(self, seconds, *, sleep):
        sleep(seconds)
        self.tick()


def stalled_clock(step=40.0):
    """A monotonic that walks past any deadline the caller sets."""
    now = {"t": 0.0}

    def monotonic():
        now["t"] += step
        return now["t"]

    return monotonic


def test_happy_path_lands_and_records(monkeypatch):
    receipt = wire_happy_path(
        monkeypatch,
        landing_states=[UNARMED, ARMED, MERGED],
    )
    outcome = land()
    assert outcome.ok
    assert outcome.exit_code == 0
    assert outcome.pr_num == "42"
    assert outcome.batch == receipt
    assert outcome.merge_sha == receipt.merge_sha
    assert not outcome.already_merged
    # Carried out of the close-out because the caller writes it straight
    # into the item's execution evidence, which is refused without it.
    assert outcome.touched_files == ("a.py",)


def test_admission_refusal_is_recoverable_and_skips_pr(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")],
            None,
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("PR machinery must not run on refusal")

    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        forbidden,
    )
    shapes = {
        "YOK-200": {
            "claims": [
                {"state": "active", "target_ids": [5]},
            ]
        },
        "YOK-150": {
            "claims": [
                {"state": "active", "target_ids": [5]},
            ]
        },
    }
    outcome = land(dispatch=dispatch_for(shapes))
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "unattested-path-overlap" in outcome.error
    assert "YOK-150" in outcome.error


def test_queue_unreadable_is_named_error(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda ctx, base_branch="main": (None, "no merge queue on 'main'"),
    )
    outcome = land(dispatch=dispatch_for({}))
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "no merge queue" in outcome.error


def test_every_poll_observation_is_announced(monkeypatch):
    """The wait is the longest step, so each observation reaches stdout's
    sibling stream rather than sitting silently in the process."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, ARMED, MERGED],
        queue_entries=(
            QueueMember(pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS"),
        ),
    )
    announced: list[str] = []
    outcome = land(emit=announced.append)
    assert outcome.ok
    assert all(line.startswith(route_mod.POLL_LINE_PREFIX) for line in announced)
    assert "queue-entry=AWAITING_CHECKS" in announced[0]
    assert "elapsed:" in announced[0]
    assert "merged=true" in announced[-1]
    # The second armed observation is the same set; repeating it hid a
    # stalled check behind elapsed time.
    assert len(announced) == 2


def test_poll_announces_only_when_the_check_set_changes(monkeypatch):
    checks = [
        ((LandingCheck("lint", "in_progress"),), None),
        ((LandingCheck("lint", "in_progress"),), None),
        ((LandingCheck("lint", "completed", "success"),), None),
    ]
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, ARMED, ARMED, ARMED, MERGED],
        queue_entries=(
            QueueMember(pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS"),
        ),
        train=TrainRun(status="in_progress", head_sha="abc123"),
    )
    monkeypatch.setattr(
        verdict_mod, "read_landing_checks",
        lambda *_a, **_k: checks.pop(0) if checks else ((LandingCheck(
            "lint", "completed", "success",
        ),), None),
    )
    announced: list[str] = []
    outcome = land(emit=announced.append)
    assert outcome.ok
    pending = [line for line in announced if "pending-checks=lint" in line]
    concluded = [line for line in announced if "concluded-checks=lint=success" in line]
    assert len(pending) == 1
    assert len(concluded) == 1
    assert "merged=true" in announced[-1]


def test_deadline_expiry_is_recoverable_and_names_the_last_observation(
    monkeypatch,
):
    wire_happy_path(monkeypatch, landing_states=[ARMED] * 100)
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=lambda _line: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error
    # The refusal repeats what the poll kept seeing, so an operator reading
    # only the final error still learns why the landing never moved.
    assert "last observed" in outcome.error
    assert "queue-entry=absent" in outcome.error


def test_landing_reads_on_the_train_schedule(monkeypatch):
    """The poll skips the stretch where the train cannot have concluded."""
    wire_happy_path(monkeypatch, landing_states=[ARMED] * 6 + [MERGED])
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(seconds):
        clock["now"] += seconds
        sleeps.append(seconds)

    outcome = land(
        sleep=sleep,
        monotonic=lambda: clock["now"],
        liveness=StubPump(),
    )
    assert outcome.ok
    # Reads at 0s, 60s, 120s, 180s, 480s, 540s — nothing in between.
    assert sleeps == [60.0, 60.0, 60.0, 300.0, 60.0]


def test_poll_keeps_the_session_live_so_the_claim_survives(monkeypatch):
    """The wait is silent, so the poll itself is the activity signal.

    Without this the stale sweep reclaims the session mid-poll and
    releases the item claim the close-out and any retry depend on.
    """
    wire_happy_path(monkeypatch, landing_states=[ARMED] * 100)
    pump = StubPump()
    land(monotonic=stalled_clock(), deadline_seconds=120.0, liveness=pump)
    assert pump.ticks >= 2


def test_queue_wait_refreshes_more_often_than_a_short_stale_ttl(monkeypatch):
    """A long scheduled sleep cannot hide a live landing from cleanup."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED] * 6 + [MERGED],
    )
    clock = {"now": 0.0}
    refreshed_at: list[float] = []

    def sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(
        liveness_mod,
        "refresh_session_heartbeat",
        lambda _session_id: refreshed_at.append(clock["now"]) or True,
    )
    pump = SessionLivenessPump(
        session_id="sess-1",
        interval_seconds=10.0,
        clock=lambda: clock["now"],
    )

    outcome = land(
        sleep=sleep,
        monotonic=lambda: clock["now"],
        liveness=pump,
    )

    assert outcome.ok
    assert clock["now"] > 15.0
    assert refreshed_at
    assert (
        max(
            later - earlier
            for earlier, later in zip([0.0, *refreshed_at], refreshed_at)
        )
        <= 10.0
    )


def test_timeout_reports_the_held_claim_and_the_resume_command(monkeypatch):
    """The printed retry has to run as-is from the state it describes."""
    wire_happy_path(monkeypatch, landing_states=[ARMED] * 100)
    monkeypatch.setattr(timeout_mod, "_ambient_session_id", lambda: "sess-1")
    resume = "yoke merge item YOK-200 --result r --verification v"
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        liveness=StubPump(),
        resume_command=resume,
        dispatch=dispatch_for({"YOK-200": {}}, holder=HELD_BY_THIS_SESSION),
    )
    assert "still held (claim 77)" in outcome.error
    assert outcome.error.endswith(resume)


def test_unchanged_failed_train_refuses_before_queue_entry(monkeypatch):
    entered: list[str] = []
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])
    monkeypatch.setattr(
        route_mod, "unchanged_failed_train_refusal",
        lambda *_a, **_k: f"{failed_train_mod.FAILED_TRAIN_UNCHANGED}: held",
    )
    monkeypatch.setattr(
        route_mod, "enter_merge_queue",
        lambda _ctx, pr_num: entered.append(pr_num) or None,
    )
    outcome = land()
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert failed_train_mod.FAILED_TRAIN_UNCHANGED in outcome.error
    assert entered == []


def test_serial_dependency_refuses_against_queued_member(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")],
            None,
        ),
    )
    shapes = {
        "YOK-200": {
            "claims": [],
            "dependencies": [
                {
                    "direction": "depends-on",
                    "other_item": "YOK-150",
                    "gate_point": "activation",
                }
            ],
        },
        "YOK-150": {"claims": []},
    }
    outcome = land(dispatch=dispatch_for(shapes))
    assert not outcome.ok
    assert "serial-ordering" in outcome.error


def test_migration_carrier_shapes_resolve_from_profile(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")],
            None,
        ),
    )
    shapes = {
        "YOK-200": {"profile": '{"state":"declared"}'},
        "YOK-150": {"profile": '{"state":"declared"}'},
    }
    outcome = land(dispatch=dispatch_for(shapes))
    assert not outcome.ok
    assert "migration-carrier-limit" in outcome.error
