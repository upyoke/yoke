"""Monitor expiry survives headless caps, default timeouts and delayed ingest."""

from datetime import timedelta
from unittest.mock import patch

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from yoke_contracts.hook_runner.client_facts import HEADLESS_LAUNCH_KEY, client_fact
from yoke_contracts.timestamps import utc_now, format_instant, parse_instant
from yoke_core.domain.observe_pre import parse_pre_event
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_monitor_deadline import monitor_timeout_seconds
from yoke_core.domain import lint_long_command_polling_monitor_duplicate as guard

SESSION = "monitor-worker"
CAPTURE = "/tmp/yoke-fleet.progress.example.log"


def payload(timeout=None, *, headless=False):
    tool_input = {"command": f"tail -f {CAPTURE}"}
    if timeout is not None:
        tool_input["timeout_ms"] = timeout
    return {
        "session_id": SESSION,
        "tool_use_id": "monitor-first",
        "tool_name": "Monitor",
        "tool_input": tool_input,
        **client_fact(HEADLESS_LAUNCH_KEY, headless),
    }


@pytest.mark.parametrize(
    "headless,requested,expected",
    [
        (False, None, 300),
        (True, None, 300),
        (False, 1800000, 1800),
        (True, 1800000, 600),
        (True, 120000, 120),
        (False, 3600000, 1800),
    ],
)
def test_effective_timeout_uses_requested_duration_and_mode(
    headless, requested, expected
):
    assert monitor_timeout_seconds(payload(requested, headless=headless)) == expected


@pytest.mark.parametrize(
    "requested,headless,lifetime",
    [
        (1800000, True, 600),
        (None, True, 300),
        (1800000, False, 1800),
    ],
)
def test_durable_deadline_allows_rearm_at_actual_expiry(
    test_db,
    requested,
    headless,
    lifetime,
):
    insert_session(test_db, SESSION)
    start = utc_now()
    envelope = parse_pre_event(payload(requested, headless=headless))
    envelope["event_time"] = format_instant(start)
    apply_envelope_state(test_db, envelope)
    # A delayed duplicate observation cannot extend the subscription clock.
    envelope["event_time"] = format_instant(start + timedelta(seconds=100))
    apply_envelope_state(test_db, envelope)
    row = test_db.execute(
        "SELECT monitor_deadline_at FROM session_tool_calls WHERE session_id=%s",
        (SESSION,),
    ).fetchone()
    assert parse_instant(row["monitor_deadline_at"]) == start + timedelta(
        seconds=lifetime
    )
    test_db.commit()
    from yoke_core.domain import db_helpers

    with (
        patch.object(db_helpers, "connect", return_value=test_db),
        patch.object(test_db, "close"),
        patch.object(guard, "utc_now", return_value=start + timedelta(seconds=10)),
    ):
        live = guard._captures_targeted_in_session("", SESSION, ("/tmp",))
        assert [(i, c) for i, c, d in live] == [("monitor-first", CAPTURE)]
    with (
        patch.object(db_helpers, "connect", return_value=test_db),
        patch.object(test_db, "close"),
        patch.object(
            guard, "utc_now", return_value=start + timedelta(seconds=lifetime)
        ),
    ):
        assert guard._captures_targeted_in_session("", SESSION, ("/tmp",)) == []
