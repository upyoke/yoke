"""Queue-routed landing orchestration: admission, record wait, close-out."""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    HELD_BY_THIS_SESSION,
    MERGED,
    UNARMED,
    dispatch_for,
    land,
    landing_record,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_failed_train as failed_train_mod
from yoke_core.domain import merge_queue_landing_timeout as timeout_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import session_liveness_pump as liveness_mod
from yoke_core.domain.merge_queue_landing_record_state import PENDING
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_pr_queue import QueueMember


AWAITING_CHECKS = (
    "pull request 42: merged=false, state=open, merge-when-ready=armed, "
    "queue-entry=AWAITING_CHECKS, mergeStateStatus=BLOCKED, "
    "failed-required-checks=none"
)


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
        members=(QueueMember(pr_num="9", head_ref="outside-yoke"),),
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
    assert any("outside-yoke" in warning for warning in outcome.warnings)


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


def test_every_changed_server_observation_is_announced(monkeypatch):
    """The wait is the longest step, so each observation reaches stdout's
    sibling stream rather than sitting silently in the process."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, ARMED, MERGED],
    )
    announced: list[str] = []
    outcome = land(
        emit=announced.append,
        landing_records=[
            landing_record(PENDING, narrative=AWAITING_CHECKS),
            landing_record(PENDING, narrative=AWAITING_CHECKS),
            landing_record(),
        ],
    )
    assert outcome.ok
    assert all(line.startswith(route_mod.POLL_LINE_PREFIX) for line in announced)
    assert "queue-entry=AWAITING_CHECKS" in announced[0]
    assert "elapsed:" in announced[0]
    assert "merged=true" in announced[-1]
    # The second armed observation is the same set; repeating it hid a
    # stalled check behind elapsed time.
    assert len(announced) == 2


def test_wait_announces_only_when_the_recorded_check_set_changes(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, ARMED, ARMED, ARMED, MERGED],
    )
    pending = f"{AWAITING_CHECKS}, pending-checks=lint concluded-checks=none"
    concluded = f"{AWAITING_CHECKS}, pending-checks=none concluded-checks=lint=success"
    announced: list[str] = []
    outcome = land(
        emit=announced.append,
        landing_records=[
            landing_record(PENDING, narrative=pending),
            landing_record(PENDING, narrative=pending),
            landing_record(PENDING, narrative=concluded),
            landing_record(),
        ],
    )
    assert outcome.ok
    pending = [line for line in announced if "pending-checks=lint" in line]
    concluded = [line for line in announced if "concluded-checks=lint=success" in line]
    assert len(pending) == 1
    assert len(concluded) == 1
    assert "merged=true" in announced[-1]


def test_deadline_expiry_is_recoverable_and_names_the_last_observation(
    monkeypatch,
):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=lambda _line: None,
        landing_records=[landing_record(PENDING, narrative=AWAITING_CHECKS)],
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error
    # The refusal repeats what the server record kept saying, so an operator
    # only the final error still learns why the landing never moved.
    assert "last observed" in outcome.error
    assert "queue-entry=AWAITING_CHECKS" in outcome.error


def test_landing_refreshes_server_records_on_the_project_cadence(monkeypatch):
    """A live waiter remains the once-per-minute trigger when relays are down."""
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(seconds):
        clock["now"] += seconds
        sleeps.append(seconds)

    outcome = land(
        sleep=sleep,
        monotonic=lambda: clock["now"],
        liveness=StubPump(),
        landing_records=[
            *[landing_record(PENDING, narrative=AWAITING_CHECKS)] * 5,
            landing_record(),
        ],
    )
    assert outcome.ok
    # The server rate-limits all lanes in this project behind the same cadence.
    assert sleeps == [60.0] * 5


def test_record_wait_keeps_the_session_live_so_the_claim_survives(monkeypatch):
    """The wait is silent, so each record cycle is the activity signal.

    Without this the stale sweep reclaims the session mid-poll and
    releases the item claim the close-out and any retry depend on.
    """
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    pump = StubPump()
    land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        liveness=pump,
        landing_records=[landing_record(PENDING, narrative=AWAITING_CHECKS)],
    )
    assert pump.ticks >= 2


def test_queue_wait_refreshes_more_often_than_a_short_stale_ttl(monkeypatch):
    """A long scheduled sleep cannot hide a live landing from cleanup."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED],
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
        landing_records=[
            landing_record(PENDING, narrative=AWAITING_CHECKS),
            landing_record(),
        ],
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
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    monkeypatch.setattr(timeout_mod, "_ambient_session_id", lambda: "sess-1")
    resume = "yoke merge item YOK-200 --result r --verification v"
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        liveness=StubPump(),
        resume_command=resume,
        dispatch=dispatch_for(
            {"YOK-200": {}},
            holder=HELD_BY_THIS_SESSION,
            landing_records=[landing_record(PENDING, narrative=AWAITING_CHECKS)],
        ),
    )
    assert "still held (claim 77)" in outcome.error
    assert outcome.error.endswith(resume)


def test_unchanged_failed_train_refuses_before_queue_entry(monkeypatch):
    entered: list[str] = []
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])
    monkeypatch.setattr(
        route_mod,
        "unchanged_failed_train_refusal",
        lambda *_a, **_k: f"{failed_train_mod.FAILED_TRAIN_UNCHANGED}: held",
    )
    monkeypatch.setattr(
        route_mod,
        "enter_merge_queue",
        lambda _ctx, pr_num: entered.append(pr_num) or None,
    )
    outcome = land()
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert failed_train_mod.FAILED_TRAIN_UNCHANGED in outcome.error
    assert entered == []
