"""Fleet-report plan-limits: one row per window, with headroom."""

from __future__ import annotations

from datetime import timedelta
import json

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    NOW,
    PLAN_LIMIT_HOST,
    PROJECT_ID,
    RELAY_HOSTNAME,
    compose,
    plan_limit_row,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_plan_capacity import (
    ALL_MODELS_LABEL,
    EMPTY,
    HEADROOM_LEGEND,
    MONTHLY_WINDOW,
    PLAN_LIMIT_HEADING,
    ROLLING_5H_WINDOW,
    ROLLING_7D_WINDOW,
    TABLE_HEADER,
    compute_plan_limit,
    format_capacity_duration,
    format_reset_utc,
    plan_limit_dicts,
    plan_limit_lines,
    plan_window_length,
    remaining_capacity,
)
from yoke_core.domain.steering_fleet_report_limits import load_plan_limits
from yoke_core.domain.steering_fleet_report_render import report_body

_NOW = "2026-09-01T13:20:00Z"
_HOST = PLAN_LIMIT_HOST


_row = plan_limit_row


def test_window_length_is_fixed_per_kind() -> None:
    assert plan_window_length("rolling_5h") == ROLLING_5H_WINDOW
    assert plan_window_length("rolling_7d") == ROLLING_7D_WINDOW
    assert plan_window_length("monthly") == MONTHLY_WINDOW
    assert plan_window_length("unknown") is None


def test_monthly_remaining_renders_to_the_minute() -> None:
    remaining = remaining_capacity(22.0, MONTHLY_WINDOW)
    assert remaining is not None
    assert format_capacity_duration(remaining) == "6d 14h 24m"


def test_worked_target_headroom_matches_format_ruling() -> None:
    cursor = compute_plan_limit(_row(), now=_NOW)
    claude = compute_plan_limit(
        _row(
            surface="claude-cli",
            plan_tier="max",
            window_kind="rolling_7d",
            remaining_percent=44.0,
            resets_at="2026-09-04T01:00:00Z",
        ),
        now=_NOW,
    )
    assert cursor.until_reset is not None
    assert claude.until_reset is not None
    assert cursor.until_reset == timedelta(days=5, hours=11, minutes=40)
    assert claude.until_reset == timedelta(days=2, hours=11, minutes=40)
    assert format_capacity_duration(cursor.until_reset) == "5d 11h 40m"
    assert format_capacity_duration(claude.until_reset) == "2d 11h 40m"
    assert cursor.headroom_percent is not None
    assert claude.headroom_percent is not None
    assert int(round(cursor.headroom_percent)) == 120
    assert int(round(claude.headroom_percent)) == 124
    assert format_reset_utc("2026-09-04T01:00:00Z") == "Sep 4 01:00"
    assert format_reset_utc("2026-09-07T01:00:00Z") == "Sep 7 01:00"


def test_plan_limit_lines_match_worked_target_table() -> None:
    lines = plan_limit_lines(
        (
            _row(
                surface="claude-cli",
                plan_tier="max",
                window_kind="rolling_7d",
                remaining_percent=44.0,
                resets_at="2026-09-04T01:00:00Z",
            ),
            _row(
                surface="codex-cli",
                plan_tier=None,
                window_kind="unknown",
                remaining_percent=None,
                resets_at=None,
                status="unknown",
                reason="usage_unreadable",
            ),
            _row(),
        ),
        now=_NOW,
    )
    assert PLAN_LIMIT_HEADING + ":" in lines
    assert TABLE_HEADER in lines
    assert (
        f"| {_HOST} | claude-cli | max | weekly · all models | 44% | 2d 11h 40m | "
        f"124% | Sep 4 01:00 |"
    ) in lines
    assert (
        f"| {_HOST} | cursor-cli | Ultra | monthly · all models | 22% | 5d 11h 40m | "
        f"120% | Sep 7 01:00 |"
    ) in lines
    assert (
        f"| {_HOST} | codex-cli | {EMPTY} | unknown | {EMPTY} | {EMPTY} | "
        f"usage_unreadable | {EMPTY} |"
    ) in lines
    assert HEADROOM_LEGEND in lines


def test_unknown_reading_has_no_headroom() -> None:
    computed = compute_plan_limit(
        _row(
            status="unknown",
            window_kind="unknown",
            remaining_percent=None,
            resets_at=None,
            reason="stale_credential",
        ),
        now=_NOW,
    )
    assert computed.headroom_percent is None
    assert computed.remaining is None


def test_past_reset_has_no_headroom() -> None:
    computed = compute_plan_limit(
        _row(resets_at="2026-08-31T13:04:00Z"),
        now=_NOW,
    )
    assert computed.headroom_percent is None


def test_rolling_five_hour_remaining_is_to_the_minute() -> None:
    remaining = remaining_capacity(89.0, ROLLING_5H_WINDOW)
    assert remaining is not None
    assert format_capacity_duration(remaining) == "4h 27m"


def test_plan_limit_dicts_carry_numeric_headroom() -> None:
    payload = plan_limit_dicts((_row(),), now=_NOW)[0]
    assert payload["scope"] == "all"
    assert payload["window_label"] == f"monthly · {ALL_MODELS_LABEL}"
    assert "headroom_percent" in payload
    assert payload["window_seconds"] == MONTHLY_WINDOW.total_seconds()
    remaining = remaining_capacity(22.0, MONTHLY_WINDOW)
    assert remaining is not None
    assert payload["remaining_seconds"] == remaining.total_seconds()
    assert int(round(payload["headroom_percent"])) == 120


def test_report_renders_table_and_unknown_without_omitting_a_failed_read(
    test_db,
) -> None:
    scope = seed_steering_scope(test_db)
    test_db.execute(
        "UPDATE session_relays SET surface_plan_limits = %s WHERE relay_id = 'relay-1'",
        (
            json.dumps(
                {
                    "claude-cli": {
                        "surface": "claude-cli",
                        "plan_tier": "max",
                        "observed_at": "2026-08-30T01:00:00Z",
                        "windows": [
                            {
                                "window_kind": "rolling_5h",
                                "scope": "all",
                                "remaining_percent": 89.0,
                                "resets_at": "2026-08-30T03:00:00Z",
                                "status": "ok",
                                "reason": None,
                            },
                            {
                                "window_kind": "rolling_7d",
                                "scope": "Fable",
                                "remaining_percent": 55.0,
                                "resets_at": "2026-09-04T01:00:00Z",
                                "status": "ok",
                                "reason": None,
                            },
                        ],
                    },
                    "cursor-cli": {
                        "surface": "cursor-cli",
                        "plan_tier": None,
                        "observed_at": "2026-08-30T01:00:00Z",
                        "windows": [
                            {
                                "window_kind": "unknown",
                                "scope": "all",
                                "remaining_percent": None,
                                "resets_at": None,
                                "status": "unknown",
                                "reason": "stale_credential",
                            }
                        ],
                    },
                }
            ),
        ),
    )
    test_db.commit()

    body = report_body(compose(scope))

    assert PLAN_LIMIT_HEADING in body
    assert TABLE_HEADER in body
    assert "claude-cli | max | rolling 5h · all models | 89%" in body
    assert "claude-cli | max | weekly · Fable | 55%" in body
    assert "cursor-cli |" in body
    assert "stale_credential" in body
    assert "do not gate launches" in body
    assert HEADROOM_LEGEND in body


_READING = {
    "claude-cli": {
        "surface": "claude-cli",
        "plan_tier": "max",
        "observed_at": "2026-08-30T01:00:00Z",
        "windows": [
            {
                "window_kind": "rolling_5h",
                "scope": "all",
                "remaining_percent": 89.0,
                "resets_at": "2026-08-30T03:00:00Z",
                "status": "ok",
                "reason": None,
            }
        ],
    }
}


def _seed_reading(test_db) -> None:
    test_db.execute(
        "UPDATE session_relays SET surface_plan_limits = %s WHERE relay_id = 'relay-1'",
        (json.dumps(_READING),),
    )
    test_db.commit()


def test_plan_limit_rows_name_the_registered_machine(test_db) -> None:
    """A steerer reads names, not UUIDs; the relay host name is the fallback."""
    seed_steering_scope(test_db)
    _seed_reading(test_db)

    named = load_plan_limits(
        test_db,
        project_id=PROJECT_ID,
        now=NOW,
        registered_names={"machine-1": "workshop-mac"},
    )
    assert {row.machine_name for row in named} == {"workshop-mac"}

    unregistered = load_plan_limits(
        test_db, project_id=PROJECT_ID, now=NOW, registered_names={}
    )
    assert {row.machine_name for row in unregistered} == {RELAY_HOSTNAME}


def test_the_report_names_machines_it_registered(test_db) -> None:
    scope = seed_steering_scope(test_db)
    _seed_reading(test_db)
    test_db.execute(
        "INSERT INTO machines (machine_id, name, owner_actor_id, "
        "access, registered_at, last_seen_at) "
        "VALUES ('machine-1', 'workshop-mac', %s, '{}', %s, %s)",
        (ACTOR_ID, NOW, NOW),
    )
    test_db.commit()

    body = report_body(compose(scope))

    assert "workshop-mac" in body
    assert "machine-1/" not in body
