"""The outcome block a merge prints when it stopped at a release wait.

Split from ``test_standalone_item_merge_close_out_report.py`` to stay under
the authored-file line budget. What these cover is one question that file
does not: a merge that is complete without being finished has to say so in a
way its reader — a worker told everywhere else to report and END — cannot
mistake for a close.
"""

from __future__ import annotations

from yoke_core.domain import (
    standalone_item_merge_close_out_report as report,
)


def test_mid_progress_work_without_a_wait_is_plainly_not_closed():
    """Only a transition that entered the release wait records the retention
    block, so a slice with nowhere to go yet owns no wait to report."""
    kind, _blocker = report.final_outcome(
        {"public_ref": "ITEM-1", "status": "implementing"},
        source_status="implementing",
        skip_status=False,
    )

    assert kind == report.NOT_CLOSED


OWES_STAGE = {
    "kind": "item_qa",
    "flow": "flow-a",
    "project": "proj",
    "stages": ["item-qa"],
    "requirement_ids": [41, 42],
}
OWES_NOTHING = {
    "kind": "none",
    "detail": "the item recorded post-deploy answer 'no_obligation'",
}
NATIVE = {"kind": "native", "surface": "claude-cli"}
OPERATOR = {"kind": "operator", "surface": "claude-desktop"}


def _body(obligation: dict, wake: dict) -> tuple[list[str], str]:
    lines = report.outcome_lines(
        {
            "public_ref": "ITEM-1",
            "status": "release",
            "item_id": 7,
            "release_wait": {
                "parked": "yes",
                "park_reason": "awaiting ITEM-1 delivery",
                "obligation": obligation,
                "wake": wake,
            },
        },
        kind=report.AWAITING_DELIVERY,
    )
    return lines, " ".join(lines)


def test_a_wakeable_owner_of_a_qa_stage_holds_and_waits_for_the_wake():
    lines, body = _body(OWES_STAGE, NATIVE)

    assert lines[0] == "ITEM-1 merged, not closed: awaiting delivery at release"
    assert "owes delivery: item-scoped QA stage item-qa (requirements 41, 42)" in body
    assert (
        "`yoke watch qa-plan -- --deployment-run-id RUN --stage item-qa "
        "--member ITEM-1 --project proj`" in body
    )
    assert "woken natively when a stage needs it" in body
    assert "do not release, do not end this session" in body
    assert "session parked: yes — awaiting ITEM-1 delivery" in body


def test_an_operator_woken_owner_is_told_no_wake_will_arrive():
    """A desktop surface is never resumed by Yoke, so promising it a wake
    leaves it waiting on something only its operator can deliver."""
    _lines, body = _body(OWES_STAGE, OPERATOR)

    assert "wake: none will arrive" in body
    assert "Yoke never resumes a claude-desktop session" in body
    assert "operator or a steering seat must re-enter it" in body
    assert "do not end this session" not in body
    assert "--stage item-qa --member ITEM-1" in body


def test_an_item_that_owes_nothing_is_not_told_to_wait():
    _lines, body = _body(OWES_NOTHING, NATIVE)

    assert "owes delivery: nothing of its own" in body
    assert "delivery closes the item itself" in body
    assert "nothing will ask this session for anything" in body
    assert "nothing is required of this session; report what landed and stop" in body
    assert "do not end this session" not in body
    assert "qa-plan" not in body


def test_an_unread_obligation_is_named_and_treated_as_owing():
    _lines, body = _body({"kind": "unread", "detail": "flow read failed"}, NATIVE)

    assert "owes delivery: not established — flow read failed" in body
    assert "yoke merge item ITEM-1 --result ... --verification ..." in body
    assert "do not release, do not end this session" in body


def test_an_unread_wake_names_why():
    _lines, body = _body(OWES_STAGE, {"kind": "unread", "surface": ""})

    assert "wake: not established (the session read named no surface)" in body


def test_an_unconfirmed_park_tells_the_owner_to_stamp_it():
    """An unrecorded wait needs a park for wake and recovery routing."""
    lines = report.outcome_lines(
        {
            "public_ref": "ITEM-1",
            "status": "release",
            "release_wait": {
                "parked": "unconfirmed (relay unavailable)",
                "park_reason": "awaiting ITEM-1 delivery",
            },
        },
        kind=report.AWAITING_DELIVERY,
    )

    body = " ".join(lines)
    assert "park unconfirmed" in body
    assert "yoke sessions touch --mode parked" in body
    assert "declare the wait so wake and recovery routing can find it" in body
