"""Fleet-report plan-limits block: remaining/reset, including unknown reads."""

from __future__ import annotations

import json

from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain.steering_fleet_report_limits import PLAN_LIMIT_HEADING
from yoke_core.domain.steering_fleet_report_render import report_body


def test_report_renders_remaining_and_unknown_without_omitting_a_failed_read(
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
                        "window_kind": "rolling_5h",
                        "remaining_percent": 89.0,
                        "resets_at": "2026-08-30T03:00:00Z",
                        "status": "ok",
                        "reason": None,
                        "observed_at": "2026-08-30T01:00:00Z",
                    },
                    "cursor-cli": {
                        "surface": "cursor-cli",
                        "plan_tier": None,
                        "window_kind": "unknown",
                        "remaining_percent": None,
                        "resets_at": None,
                        "status": "unknown",
                        "reason": "stale_credential",
                        "observed_at": "2026-08-30T01:00:00Z",
                    },
                }
            ),
        ),
    )
    test_db.commit()

    body = report_body(compose(scope))

    assert PLAN_LIMIT_HEADING in body
    assert "claude-cli  max  89% remaining  rolling_5h  resets 2026-08-30T03:00:00Z" in body
    assert "cursor-cli  unknown  stale_credential" in body
    assert "do not gate launches" in body
