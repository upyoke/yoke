"""An unreadable plan-limit reading earns guidance its own reason establishes."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_session_message_support import message_connection
from runtime.api.steering_fleet_test_helpers import plan_limit_row
from yoke_contracts.session_control.plan_limit_unreadable_guidance import (
    CREDENTIAL_GUIDANCE,
    READ_FAILED_GUIDANCE,
    RELAY_UPDATE_GUIDANCE,
    THROTTLED_GUIDANCE,
    unreadable_guidance,
    unreadable_note,
    with_unreadable_guidance,
)
from yoke_contracts.session_control.plan_limits import (
    RELAY_PREDATES_WINDOWS_REASON,
    plan_limit_window,
    sanitize_plan_limits,
    unknown_reading,
)
from yoke_core.domain.session_relay_read import list_visible_relays
from yoke_core.domain.steering_fleet_plan_capacity import (
    plan_limit_dicts,
    plan_limit_lines,
)

_NOW = "2026-09-01T13:20:00.000000Z"
_REASON_CLASSES = (
    ("stale_credential", CREDENTIAL_GUIDANCE),
    ("codex_auth_missing_tokens", CREDENTIAL_GUIDANCE),
    ("app_server_timeout+stale_credential", CREDENTIAL_GUIDANCE),
    ("http_429", THROTTLED_GUIDANCE),
    ("app_server_timeout+http_429", THROTTLED_GUIDANCE),
    ("http_503", READ_FAILED_GUIDANCE),
    ("http_403", READ_FAILED_GUIDANCE),
    ("http_read_failed_TimeoutError", READ_FAILED_GUIDANCE),
    ("http_body_not_an_object", READ_FAILED_GUIDANCE),
    ("usage_unreadable", READ_FAILED_GUIDANCE),
    ("probe_raised_ValueError", READ_FAILED_GUIDANCE),
    (RELAY_PREDATES_WINDOWS_REASON, RELAY_UPDATE_GUIDANCE),
    (None, READ_FAILED_GUIDANCE),
)


@pytest.mark.parametrize(("reason", "guidance"), _REASON_CLASSES)
def test_each_reason_class_earns_its_own_guidance(reason, guidance) -> None:
    assert unreadable_guidance(reason) == guidance


def test_only_a_credential_reason_says_to_sign_in_again() -> None:
    assert "re-authenticate" in CREDENTIAL_GUIDANCE
    for guidance in (THROTTLED_GUIDANCE, READ_FAILED_GUIDANCE, RELAY_UPDATE_GUIDANCE):
        assert "re-authenticate" not in guidance
    # A throttled read establishes nothing about the sign-in, and says so.
    assert "not known to be signed out" in THROTTLED_GUIDANCE
    assert "retries on the next refresh" in THROTTLED_GUIDANCE
    assert "retries on the next refresh" in READ_FAILED_GUIDANCE


def test_no_guidance_claims_a_launch_will_fail() -> None:
    # A plan-limit read is informational and never gates a launch, so no
    # reason it reports can establish that one fails.
    for _, guidance in _REASON_CLASSES:
        assert "launch" not in guidance


@pytest.mark.parametrize(("reason", "guidance"), _REASON_CLASSES)
def test_the_steering_table_shows_the_reason_beside_its_guidance(
    reason, guidance
) -> None:
    row = plan_limit_row(
        surface="claude-cli",
        plan_tier=None,
        window_kind="unknown",
        remaining_percent=None,
        resets_at=None,
        status="unknown",
        reason=reason,
    )

    lines = plan_limit_lines((row,), now=_NOW)
    cells = [cell.strip() for cell in lines[3].split("|")]

    assert cells[-3] == unreadable_note(reason)
    assert cells[-3] == f"{reason or 'unreadable'} — {guidance}"
    assert plan_limit_dicts((row,), now=_NOW)[0]["guidance"] == guidance


def test_a_throttled_steering_row_never_says_to_sign_in_again() -> None:
    row = plan_limit_row(
        surface="claude-cli",
        window_kind="unknown",
        remaining_percent=None,
        resets_at=None,
        status="unknown",
        reason="http_429",
    )

    body = "\n".join(plan_limit_lines((row,), now=_NOW))

    assert "http_429 — the vendor throttled the limits check" in body
    assert "re-authenticate" not in body


def test_a_readable_window_carries_no_guidance() -> None:
    readings = sanitize_plan_limits(
        {
            "claude-cli": {
                "plan_tier": "max",
                "observed_at": _NOW,
                "windows": [
                    plan_limit_window(
                        window_kind="rolling_5h",
                        scope="all",
                        meter="session",
                        remaining_percent=89.0,
                        resets_at="2026-09-01T15:00:00.000000Z",
                    )
                ],
            }
        }
    )

    guided = with_unreadable_guidance(readings)

    assert guided == readings
    assert plan_limit_dicts((plan_limit_row(),), now=_NOW)[0]["guidance"] is None


def test_the_machines_roster_serves_guidance_with_each_unreadable_window() -> None:
    conn = message_connection()
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state,surface_plan_limits) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "machine:ada",
            10,
            "11111111-1111-4111-8111-111111111111",
            "ada-studio",
            "launch.271",
            json.dumps({"claude-cli": "2.1"}),
            json.dumps([1]),
            "2026-08-22T12:00:00.000000Z",
            "2026-08-22T12:01:00.000000Z",
            "2026-08-22T12:03:00.000000Z",
            "active",
            json.dumps(
                {
                    "claude-cli": unknown_reading(
                        "claude-cli",
                        "http_429",
                        observed_at="2026-08-22T12:01:00.000000Z",
                    )
                }
            ),
        ),
    )
    conn.commit()

    (relay,) = list_visible_relays(conn, actor_id=10, now="2026-08-22T12:02:00.000000Z")

    (window,) = relay["plan_limits"]["claude-cli"]["windows"]
    assert window["reason"] == "http_429"
    assert window["guidance"] == THROTTLED_GUIDANCE
