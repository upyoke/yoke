"""An empty included meter wakes its owner when paid extra usage can bill it."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
)
from runtime.api.domain.test_session_wake_exhausted_meter import (
    _ABSENT,
    CREDITS,
    DISABLED,
    FRESH_FOR_WAKE,
    WAKE_AT,
    _pin,
    _queue_stopped_codex,
    _reading,
    _rolling,
)
from yoke_contracts.session_control.extra_usage import EXTRA_CAP_REACHED, extra_usage
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_wake_meter import (
    SKIP_METER_EXHAUSTED,
    overlay_resume_state,
    refuse_exhausted_wake,
)


def test_included_zero_with_codex_credits_wakes_the_same_owner_once() -> None:
    conn = message_connection()
    message_id = _queue_stopped_codex(conn, 0.0, extra=CREDITS)

    candidates = wake_eligible_recipients(conn, now=WAKE_AT)

    assert [(c["message_id"], c["session_id"]) for c in candidates] == [
        (message_id, NATIVE_WAKE_SESSION_ID)
    ]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE result_code=?",
            (SKIP_METER_EXHAUSTED,),
        ).fetchone()[0]
        == 0
    )


def test_a_restored_extra_usage_reading_releases_a_skipped_owner() -> None:
    conn = message_connection()
    message_id = _queue_stopped_codex(conn, 0.0)
    assert wake_eligible_recipients(conn, now=WAKE_AT) == []
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits=? WHERE relay_id=?",
        (
            json.dumps(
                {
                    "codex-cli": _reading(
                        "codex-cli", _rolling("primary", 0.0), CREDITS, FRESH_FOR_WAKE
                    )
                }
            ),
            "machine:m4",
        ),
    )
    conn.commit()

    candidates = wake_eligible_recipients(conn, now=WAKE_AT)

    assert [c["message_id"] for c in candidates] == [message_id]


@pytest.mark.parametrize(
    ("extra", "observed_at"),
    [
        (_ABSENT, NOW_TEXT),
        (extra_usage("unknown", meter="unknown", reason="http_503"), NOW_TEXT),
        (DISABLED, "2026-08-22T15:50:00.000000Z"),
    ],
    ids=["relay-predates-extra-usage", "unreadable", "stale-disabled"],
)
def test_unproven_extra_usage_is_not_exhaustion(extra, observed_at) -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="claude-cli",
        model="claude-opus-4-6",
        machine_id="m2",
        project_id=1,
        windows=_rolling("five_hour", 0.0),
        extra=extra,
        observed_at=observed_at,
    )

    assert refuse_exhausted_wake(conn, "s2", NOW) is None
    assert overlay_resume_state(conn, "s2", "resumed-died", NOW) == "resumed-died"


def test_a_reached_spending_cap_blocks_even_with_a_balance() -> None:
    conn = message_connection()
    _pin(
        conn,
        "s2",
        surface="codex-cli",
        model="gpt-5",
        machine_id="m2",
        project_id=1,
        windows=_rolling("primary", 0.0),
        extra=extra_usage(
            EXTRA_CAP_REACHED,
            meter="rateLimits.spendControlReached",
            balance=12.5,
            units="Codex credits",
            reason="spend_control_reached",
        ),
    )

    refused = refuse_exhausted_wake(conn, "s2", NOW)

    assert refused is not None
    assert "extra usage cap reached" in str(refused)
    assert "spend_control_reached" in str(refused)
