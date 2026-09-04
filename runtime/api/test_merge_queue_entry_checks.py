"""Red required checks are terminal; a set still running keeps the budget."""

from runtime.api.merge_queue_landing_test_helpers import (
    land,
    landing_record,
    wire_happy_path,
)
from runtime.api.test_merge_queue_route import stalled_clock

from yoke_core.domain import merge_queue_entry_checks as checks_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_record import from_readback
from yoke_core.domain.merge_queue_landing_record_state import (
    ENTRY_CHECKS_FAILED,
    PENDING,
)
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState

RED_ARMED = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="blocked",
    head_sha="a" * 40,
)

RUN_URL = "https://github.com/o/r/actions/runs/1/job/2"

FAILED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="failure",
    required=True,
    url=RUN_URL,
)
PENDING_REQUIRED = LandingCheck(name="test-shard", status="in_progress", required=True)
FAILED_OPTIONAL = LandingCheck(
    name="reuse-coverage", status="completed", conclusion="failure"
)


NOT_QUEUED = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")
IN_QUEUE = PrQueueMembership(
    in_queue=True,
    entry_state="AWAITING_CHECKS",
    mergeable="MERGEABLE",
)


def _record(*, state=RED_ARMED, membership=NOT_QUEUED, checks=()):
    return from_readback(
        item_id=1,
        project_id=1,
        pr_number="42",
        readback=LandingReadback(
            state=state,
            membership=membership,
            required_checks=checks,
        ),
        observed_at="2026-09-04T01:00:00Z",
    )


def test_a_red_required_check_ends_the_wait_without_the_poll_budget(monkeypatch):
    """The named case: BLOCKED plus one red required check is not a wait."""
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED])
    announced: list[str] = []
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=announced.append,
        landing_records=[
            landing_record(
                ENTRY_CHECKS_FAILED,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=armed_not_enqueued, "
                    "concluded-checks=repo-contracts=failure"
                ),
                head_sha="a" * 40,
                failed_checks=(FAILED_REQUIRED,),
                disarm_note="merge-when-ready disarmed",
            )
        ],
    )
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "entry-checks-failed" in outcome.error
    # The check and the run that explains it, so the holder does not have
    # to read `gh pr checks` by hand to find out what went red.
    assert "repo-contracts=failure" in outcome.error
    assert RUN_URL in outcome.error
    assert "re-run the verification gate" in outcome.error
    assert "merge-when-ready disarmed" in outcome.error
    assert "did not merge within" not in outcome.error
    assert any("concluded-checks=repo-contracts=failure" in x for x in announced)


def test_recorded_checks_still_running_spend_the_wait_budget(monkeypatch):
    """BLOCKED with everything pending is the ordinary armed-and-waiting."""
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED])
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=lambda _line: None,
        landing_records=[
            landing_record(
                PENDING,
                narrative=(
                    "pull request 42: merged=false, state=open, "
                    "queue-entry=armed_not_enqueued, "
                    "pending-checks=test-shard"
                ),
            )
        ],
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error
    assert "pending-checks=test-shard" in outcome.error


def test_a_failed_optional_check_does_not_refuse_the_entry():
    """Only the checks GitHub gates the entry on can make it impossible."""
    assert checks_mod.failed_required_checks((FAILED_OPTIONAL,)) == ()


def test_a_successful_required_check_is_not_red():
    green = LandingCheck("ci", "completed", "success", required=True)
    assert checks_mod.failed_required_checks((green,)) == ()


def test_unreadable_or_empty_checks_are_not_red():
    assert checks_mod.failed_required_checks(None) == ()
    assert checks_mod.failed_required_checks(()) == ()


def test_a_red_required_check_is_terminal_on_one_record():
    record = _record(checks=(FAILED_REQUIRED, PENDING_REQUIRED))
    assert record.state == ENTRY_CHECKS_FAILED
    assert "failed-required-checks=repo-contracts=failure" in record.narrative
    assert record.head_sha == "a" * 40
    assert record.failed_checks == (FAILED_REQUIRED,)


def test_checks_still_running_keep_the_wait_budget():
    record = _record(checks=(PENDING_REQUIRED,))
    assert record.state == PENDING
    assert "failed-required-checks=none" in record.narrative


def test_an_unreadable_rollup_keeps_the_wait_budget():
    """An unreadable rollup proves nothing, so it cannot end the wait."""
    record = from_readback(
        item_id=1,
        project_id=1,
        pr_number="42",
        readback=LandingReadback(
            state=RED_ARMED,
            membership=NOT_QUEUED,
            required_checks=None,
            checks_error="required-checks read failed: transport",
        ),
        observed_at="2026-09-04T01:00:00Z",
    )
    assert record.state == PENDING
    assert "required-checks read failed" in record.narrative


def test_unarmed_red_required_checks_are_terminal():
    unarmed = PrLandingState(
        merged=False, closed=False, auto_merge_active=False, head_sha="a" * 40
    )
    record = _record(state=unarmed, checks=(FAILED_REQUIRED,))
    assert record.state == ENTRY_CHECKS_FAILED
    assert record.head_sha == "a" * 40


def test_a_queue_entry_outranks_a_stale_red_check_read():
    """An explicit queue entry means GitHub is still driving the landing."""
    assert _record(membership=IN_QUEUE, checks=(FAILED_REQUIRED,)).state == PENDING
