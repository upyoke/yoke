"""Staffing decisions for unpicked steering-scope work."""

from __future__ import annotations

from yoke_core.domain.steering_backstop_selection import (
    WITHHELD_ALREADY_STAFFED,
    WITHHELD_BUDGET_EXHAUSTED,
    WITHHELD_WITHIN_GRACE,
    BackstopCandidate,
    backstop_idempotency_key,
    backstop_instruction,
    select_backstop_work,
)


NOW = "2026-08-26T12:00:00Z"
GRACE_SECONDS = 20 * 60


def candidate(
    item_id: int,
    *,
    unpicked_since: str,
    rank: int = 0,
    next_step: str = "advance",
) -> BackstopCandidate:
    return BackstopCandidate(
        item_id=item_id,
        item_ref=f"TST-{item_id}",
        title=f"item {item_id}",
        next_step=next_step,
        rank=rank,
        unpicked_since=unpicked_since,
    )


def test_work_past_the_grace_period_is_staffed_up_to_the_budget():
    selection = select_backstop_work(
        [
            candidate(1, unpicked_since="2026-08-26T11:00:00Z", rank=0),
            candidate(2, unpicked_since="2026-08-26T10:00:00Z", rank=1),
            candidate(3, unpicked_since="2026-08-26T09:00:00Z", rank=2),
        ],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=2,
    )

    assert [item.item_id for item in selection.staff] == [1, 2]
    assert selection.headroom == 2
    assert [entry.candidate.item_id for entry in selection.withheld] == [3]
    assert selection.withheld[0].reason == WITHHELD_BUDGET_EXHAUSTED


def test_work_still_inside_the_grace_period_is_left_for_a_person():
    selection = select_backstop_work(
        [candidate(4, unpicked_since="2026-08-26T11:55:00Z")],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=2,
    )

    assert selection.staff == ()
    assert selection.withheld[0].reason == WITHHELD_WITHIN_GRACE
    assert selection.withheld[0].unpicked_seconds == 300


def test_a_spent_budget_staffs_nothing():
    selection = select_backstop_work(
        [candidate(5, unpicked_since="2026-08-26T09:00:00Z")],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=2,
        staffed_item_ids=(90, 91),
    )

    assert selection.staff == ()
    assert selection.headroom == 0
    assert selection.withheld[0].reason == WITHHELD_BUDGET_EXHAUSTED


def test_work_a_staffed_worker_is_already_coming_for_is_skipped():
    selection = select_backstop_work(
        [
            candidate(6, unpicked_since="2026-08-26T09:00:00Z", rank=0),
            candidate(7, unpicked_since="2026-08-26T09:00:00Z", rank=1),
        ],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=2,
        staffed_item_ids=(6,),
    )

    assert [item.item_id for item in selection.staff] == [7]
    assert selection.withheld[0].reason == WITHHELD_ALREADY_STAFFED
    assert selection.workers_in_flight == 1


def test_staffing_follows_scheduler_rank_not_input_order():
    selection = select_backstop_work(
        [
            candidate(11, unpicked_since="2026-08-26T09:00:00Z", rank=2),
            candidate(12, unpicked_since="2026-08-26T09:00:00Z", rank=0),
        ],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=1,
    )

    assert [item.item_id for item in selection.staff] == [12]


def test_no_candidates_reports_headroom_without_staffing():
    selection = select_backstop_work(
        [],
        now=NOW,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=3,
        staffed_item_ids=(99,),
    )

    assert selection.staff == ()
    assert selection.withheld == ()
    assert selection.headroom == 2
    assert selection.to_dict()["worker_budget"] == 3


def test_the_instruction_names_the_route_the_item_and_the_report_recipient():
    body = backstop_instruction(
        candidate(8, unpicked_since="2026-08-26T09:00:00Z", next_step="conduct"),
        report_to_session_id="steering-session",
    )

    assert body.splitlines()[0] == "/yoke conduct TST-8"
    assert "execute only TST-8 to done" in body
    assert "yoke say --stdin --session steering-session" in body
    assert "DONE TST-8" in body


def test_one_gap_has_one_key_so_re_evaluation_cannot_double_launch():
    assert backstop_idempotency_key(3, 42) == "steering-backstop:3:42"
    assert backstop_idempotency_key(3, 42) == backstop_idempotency_key(3, 42)
    assert backstop_idempotency_key(3, 42) != backstop_idempotency_key(4, 42)
