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


def test_the_release_wait_outcome_names_the_retention_and_the_re_entry():
    lines = report.outcome_lines(
        {
            "public_ref": "ITEM-1",
            "status": "release",
            "item_id": 7,
            "release_wait": {
                "parked": "yes",
                "park_reason": "awaiting ITEM-1 delivery",
            },
        },
        kind=report.AWAITING_DELIVERY,
    )

    assert lines[0] == "ITEM-1 merged, not closed: awaiting delivery at release"
    body = " ".join(lines)
    assert "do not release, do not end this session" in body
    assert "session parked: yes — awaiting ITEM-1 delivery" in body
    assert "yoke merge item ITEM-1 --result ... --verification ..." in body


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
