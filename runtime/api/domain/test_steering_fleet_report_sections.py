"""One holder, one row: which section names a holder, and only one does.

The claim inventory and every holder alarm render the same row shape, and an
empty section renders nothing at all, so an inventory that listed every
holder printed a byte-identical row directly beneath the alarm that had just
named it. A steerer read one quiet holder as two sessions in trouble, and
read the inventory's below-threshold rows as more rows under the idle
heading, which promises no tool call in over twenty minutes.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    IDLE_SECONDS,
    JUST_NOW,
    WORKER_SESSION,
    compose as _compose,
    seed_session,
    seed_steering_scope,
    seed_tool_call,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.steering_fleet_report_sections import (
    CLAIMS_HEADING,
    unlisted_holders,
)
from yoke_core.domain.work_claim_targets import make_item_target


#: Ten minutes before ``NOW``: quiet, but nowhere near :data:`IDLE_SECONDS`.
BELOW_THRESHOLD = "2026-08-26T11:50:00Z"

MERGE_WAIT = "cd /repo && yoke watch merge merge-item -- YOK-2 --wait"


@pytest.fixture
def fleet(test_db):
    """One holder quiet for three hours, so the idle alarm names it."""
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    return conn


def _claim(conn, session_id: str, *, item_id: int, last_tool_call_at: str) -> None:
    seed_session(conn, session_id, last_tool_call_at=last_tool_call_at)
    conn.commit()
    claim_work(conn, session_id=session_id, target=make_item_target(item_id))


def _rows_naming(body: str, session_id: str) -> list[str]:
    return [line for line in body.splitlines() if session_id in line]


def test_an_idle_holder_is_named_once_rather_than_twice(fleet):
    body = report_body(_compose(fleet))

    assert len(_rows_naming(body, WORKER_SESSION)) == 1
    assert "idle holders" in body
    assert CLAIMS_HEADING not in body


def test_a_holder_below_the_idle_threshold_is_not_printed_under_that_heading(fleet):
    """A quiet-10m row under a heading promising over-20m is the false read."""
    _claim(fleet, "recent-worker", item_id=2, last_tool_call_at=BELOW_THRESHOLD)

    body = report_body(_compose(fleet))
    lines = body.splitlines()
    idle_heading = next(i for i, line in enumerate(lines) if "idle holders" in line)
    claims_heading = next(i for i, line in enumerate(lines) if CLAIMS_HEADING in line)
    recent_row = next(i for i, line in enumerate(lines) if "recent-worker" in line)

    assert idle_heading < claims_heading < recent_row


def test_the_inventory_heading_says_quiet_there_carries_no_alarm(fleet):
    """The rows below it are quiet by the same measure and mean nothing by it."""
    _claim(fleet, "recent-worker", item_id=2, last_tool_call_at=BELOW_THRESHOLD)

    body = report_body(_compose(fleet))

    heading = next(line for line in body.splitlines() if CLAIMS_HEADING in line)
    assert "every other holder" in heading
    assert "quiet here is no alarm" in heading


def test_a_holder_inside_a_long_call_is_named_only_in_the_in_flight_section(fleet):
    seed_tool_call(
        fleet,
        WORKER_SESSION,
        tool_use_id="call-1",
        started_at="2026-08-26T11:40:00Z",
        command_summary=MERGE_WAIT,
    )
    fleet.commit()

    body = report_body(_compose(fleet))

    assert len(_rows_naming(body, WORKER_SESSION)) == 1
    assert "in watch merge since" in body
    assert "idle holders" not in body
    assert CLAIMS_HEADING not in body


def test_a_working_holder_appears_in_the_inventory_and_no_alarm(fleet):
    _claim(fleet, "busy-worker", item_id=2, last_tool_call_at=JUST_NOW)

    report = _compose(fleet)
    body = report_body(report)

    assert [holder.session_id for holder in unlisted_holders(report)] == ["busy-worker"]
    assert len(_rows_naming(body, "busy-worker")) == 1
    assert body.index(CLAIMS_HEADING) < body.index("busy-worker")


def test_the_inventory_disappears_when_every_holder_is_already_named(fleet):
    """An empty section costs the steerer nothing, so it prints nothing."""
    report = _compose(fleet)

    assert [holder.session_id for holder in report.holders] == [WORKER_SESSION]
    assert unlisted_holders(report) == ()
    assert CLAIMS_HEADING not in report_body(report)


def test_every_row_under_the_idle_heading_is_past_the_number_it_states(fleet):
    """A heading naming a number no row below it was tested against is the defect."""
    _claim(fleet, "recent-worker", item_id=2, last_tool_call_at=BELOW_THRESHOLD)

    report = _compose(fleet)

    assert report.idle_after_seconds == IDLE_SECONDS
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}
    assert all(holder.idle_seconds >= IDLE_SECONDS for holder in report.idle)


def test_the_actionable_digest_drops_the_inventory_it_no_longer_renders(fleet):
    """The digest trims that section by length; a stale length ate a finding."""
    from yoke_core.domain.steering_fleet_report_render import scope_actionable_digest

    _claim(fleet, "busy-worker", item_id=2, last_tool_call_at=JUST_NOW)

    digest = scope_actionable_digest(_compose(fleet))

    assert "busy-worker" not in digest
    assert CLAIMS_HEADING not in digest
    assert WORKER_SESSION in digest
    assert "idle holders" in digest
