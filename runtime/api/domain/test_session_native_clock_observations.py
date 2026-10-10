"""Native session observations retain chronology across database timezones."""

from datetime import timedelta
import json

import pytest

from yoke_contracts.timestamps import parse_instant, format_instant
from yoke_contracts.session_control.presentation import (
    PRESENTATION_MODE_BIDIRECTIONAL,
    PRESENTATION_SOURCE_CLAUDE_JOB_STATE,
    PRESENTATION_STATE_ATTACHED,
    PRESENTATION_STATE_NOT_ATTACHED,
    PRESENTATION_SURFACE_REMOTE_CONTROL,
)
from yoke_core.domain.session_presentation_observation import (
    record_session_presentation,
)
from runtime.api.domain.coordination_claim_test_support import seed_session

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


def payload(clock, attached):
    return json.dumps(
        {
            "presentation_surface": PRESENTATION_SURFACE_REMOTE_CONTROL
            if attached
            else None,
            "presentation_state": PRESENTATION_STATE_ATTACHED
            if attached
            else PRESENTATION_STATE_NOT_ATTACHED,
            "presentation_mode": PRESENTATION_MODE_BIDIRECTIONAL if attached else None,
            "presentation_source": PRESENTATION_SOURCE_CLAUDE_JOB_STATE,
            "presentation_observed_at": format_instant(clock),
        }
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_material_presentation_changes_compare_native_microseconds(test_db, zone):
    seed_session(test_db, "native-presentation")
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    assert record_session_presentation(
        test_db, session_id="native-presentation", payload_json=payload(STAMP, True)
    )
    newer = STAMP + timedelta(microseconds=1)
    assert record_session_presentation(
        test_db, session_id="native-presentation", payload_json=payload(newer, False)
    )
    assert not record_session_presentation(
        test_db, session_id="native-presentation", payload_json=payload(STAMP, True)
    )
    row = test_db.execute(
        "SELECT presentation_state, presentation_observed_at FROM harness_sessions WHERE session_id=%s",
        ("native-presentation",),
    ).fetchone()
    assert tuple(row) == (PRESENTATION_STATE_NOT_ATTACHED, newer)


def test_naive_external_presentation_clock_is_rejected(test_db):
    raw = json.loads(payload(STAMP, True))
    raw["presentation_observed_at"] = "2026-10-09T03:00:00"
    assert not record_session_presentation(
        test_db, session_id="absent-session", payload_json=json.dumps(raw)
    )
