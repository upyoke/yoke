"""What a vendor-stopped row tells the seat, and when it demands anything.

The row exists because every other detector reads a session the provider
stopped as a worker quietly thinking. Getting that visible is only half of
it: a seat that reads five rows and can act on none of them stops reading
the section, so the line has to separate the ones the relay is already
handling from the ones nobody is coming for — and only the second kind may
make the report actionable.
"""

from __future__ import annotations

from dataclasses import replace

from runtime.api.domain.test_steering_fleet_report_populated_body import (
    _populated_report,
    report_body,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render_vendor_errors import MESSAGE_LIMIT
from yoke_core.domain.steering_fleet_report_vendor_errors import VendorErrorSession


LIVE_ERROR = (
    "unexpected status 404 Not Found: Unknown error, url: "
    "https://chatgpt.com/backend-api/codex/responses"
)


def _stopped(**overrides) -> VendorErrorSession:
    fields = {
        "session_id": "stopped-session",
        "item_id": 41,
        "public_ref": "YOK-41",
        "signature_id": "client_refused",
        "error_message": LIVE_ERROR,
        "observed_at": "2026-09-03T15:03:29Z",
        "stopped_seconds": 720,
        "status": "waiting_backoff",
        "reason": "the provider refused this client build",
        "due_at": "2026-09-03T15:08:29Z",
        "attempts": 1,
        "budget": 3,
        "executor_surface": "codex-cli",
        "executor_version": "0.151.0-alpha.7.2",
    }
    fields.update(overrides)
    return VendorErrorSession(**fields)


def _row(**overrides) -> str:
    entry = _stopped(**overrides)
    body = report_body(replace(_populated_report(), vendor_errors=(entry,)))
    return next(line for line in body.splitlines() if entry.session_id in line)


def test_the_row_names_the_session_its_item_the_failure_and_when():
    line = _row()

    assert "YOK-41" in line
    assert "stopped-session" in line
    assert "client_refused" in line
    assert "404 Not Found" in line
    assert "stopped 12m ago" in line


def test_a_session_the_relay_will_retry_says_so_and_asks_nothing():
    line = _row(status="waiting_backoff", attempts=1)

    assert "relay resumes it at 2026-09-03T15:08:29Z" in line
    assert "attempt 2 of 3" in line


def test_a_fleet_with_nothing_stopped_renders_no_section():
    body = report_body(replace(_populated_report(), vendor_errors=()))

    assert "vendor-stopped" not in body


def test_a_spent_budget_hands_the_session_to_the_seat_by_name():
    line = _row(status="budget_spent", attempts=3)

    assert "3 resumes spent" in line
    assert "yours" in line


def test_a_failure_no_retry_can_move_says_that_instead_of_a_count():
    line = _row(
        status="seat_required",
        signature_id="quota_exhausted",
        reason="the account's usage window is exhausted",
        attempts=0,
        budget=0,
    )

    assert "the account's usage window is exhausted" in line
    assert "no retry can move this" in line
    assert "attempt" not in line


def test_a_working_session_is_shown_but_never_offered_as_a_resume():
    line = _row(status="turn_in_flight")

    assert "inside an unreturned tool call" in line
    assert "no resume" in line


def test_a_long_provider_message_does_not_push_the_rest_off_the_line():
    line = _row(error_message="boom " * 60)

    assert "…" in line
    assert "stopped 12m ago" in line
    assert len(line.split("client_refused: ")[1].split("  stopped")[0]) == MESSAGE_LIMIT


def test_only_a_session_nobody_is_coming_for_makes_the_report_actionable():
    quiet = replace(
        _populated_report(),
        available=(),
        idle=(),
        starved=(),
        unregistered_launches=(),
        landed_open=(),
        suspected_orphaned_waiters=(),
        dead_waits=(),
        messages_awaiting_seat=0,
    )

    handled = replace(quiet, vendor_errors=(_stopped(status="waiting_backoff"),))
    assert handled.actionable is False
    assert handled.vendor_errors_needing_action() == ()

    stranded = replace(quiet, vendor_errors=(_stopped(status="budget_spent"),))
    assert stranded.actionable is True


def test_the_projection_carries_every_fact_the_line_renders():
    report = replace(_populated_report(), vendor_errors=(_stopped(),))

    entry = report_dict(report)["vendor_errors"][0]

    assert entry["public_ref"] == "YOK-41"
    assert entry["signature_id"] == "client_refused"
    assert entry["error_message"] == LIVE_ERROR
    assert entry["observed_at"] == "2026-09-03T15:03:29Z"
    assert entry["status"] == "waiting_backoff"
    assert entry["due_at"] == "2026-09-03T15:08:29Z"
    assert entry["attempts"] == 1
    assert entry["budget"] == 3
    assert entry["executor_version"] == "0.151.0-alpha.7.2"
    assert entry["seat_owed"] is False


def test_the_fingerprint_moves_when_a_row_changes_status_not_when_it_waits():
    waiting = replace(_populated_report(), vendor_errors=(_stopped(),))
    older = replace(
        _populated_report(),
        vendor_errors=(_stopped(stopped_seconds=3600),),
    )
    spent = replace(
        _populated_report(),
        vendor_errors=(_stopped(status="budget_spent", attempts=3),),
    )

    assert waiting.fingerprint() == older.fingerprint()
    assert waiting.fingerprint() != spent.fingerprint()
