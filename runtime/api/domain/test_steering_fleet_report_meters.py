"""Vendor-meter rows and their live model selections."""

from __future__ import annotations

import json

from runtime.api.steering_fleet_test_helpers import (
    compose,
    plan_limit_row,
    seed_steering_scope,
)
from yoke_contracts.session_control.plan_limits import (
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
)
from yoke_core.domain.steering_fleet_plan_capacity import (
    plan_limit_dicts,
    plan_limit_lines,
)
from yoke_core.domain.steering_fleet_report_capacity import SessionCount
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_render import report_body


_NOW = "2026-09-01T13:20:00Z"
_CURSOR_METER = "planUsage.autoPercentUsed"
_OTHER_METER = "planUsage.apiPercentUsed"


def _count(model: str) -> SessionCount:
    return SessionCount(
        machine_id="machine-1",
        surface="cursor-cli",
        count=1,
        requested_model=model,
        requested_reasoning_effort="high",
        requested_context_window_tokens=200_000,
        model=model,
        reasoning_effort="high",
        context_window_tokens=200_000,
    )


def _cursor_limits() -> tuple[MachinePlanLimit, MachinePlanLimit]:
    return (
        plan_limit_row(
            scope=CURSOR_MODELS_SCOPE,
            meter=_CURSOR_METER,
            remaining_percent=0.0,
        ),
        plan_limit_row(
            scope=CURSOR_OTHER_MODELS_SCOPE,
            meter=_OTHER_METER,
            remaining_percent=89.9,
        ),
    )


def test_cursor_models_render_beside_their_enforced_pool() -> None:
    counts = (
        _count("composer-1"),
        _count("cursor-grok-3"),
        _count("claude-opus-4-6"),
    )
    lines = plan_limit_lines(_cursor_limits(), now=_NOW, session_counts=counts)
    cursor_line = next(line for line in lines if f"| {_CURSOR_METER} |" in line)
    other_line = next(line for line in lines if f"| {_OTHER_METER} |" in line)

    assert "composer-1" in cursor_line
    assert "cursor-grok-3" in cursor_line
    assert "claude-opus-4-6" not in cursor_line
    assert "claude-opus-4-6" in other_line
    assert "composer-1" not in other_line
    assert "cursor-grok-3" not in other_line

    payload = {
        row["meter"]: row
        for row in plan_limit_dicts(_cursor_limits(), now=_NOW, session_counts=counts)
    }
    assert len(payload[_CURSOR_METER]["live_model_selections"]) == 2
    assert len(payload[_OTHER_METER]["live_model_selections"]) == 1


def test_report_renders_cursor_pools_as_distinct_meter_rows(test_db) -> None:
    scope = seed_steering_scope(test_db)
    test_db.execute(
        "UPDATE session_relays SET surface_plan_limits = %s WHERE relay_id = 'relay-1'",
        (
            json.dumps(
                {
                    "cursor-cli": {
                        "surface": "cursor-cli",
                        "plan_tier": "Ultra",
                        "observed_at": "2026-09-01T13:19:00Z",
                        "windows": [
                            {
                                "window_kind": "monthly",
                                "scope": CURSOR_MODELS_SCOPE,
                                "meter": _CURSOR_METER,
                                "remaining_percent": 0.0,
                                "resets_at": "2026-09-07T01:00:00Z",
                                "status": "ok",
                                "reason": None,
                            },
                            {
                                "window_kind": "monthly",
                                "scope": CURSOR_OTHER_MODELS_SCOPE,
                                "meter": _OTHER_METER,
                                "remaining_percent": 89.9,
                                "resets_at": "2026-09-07T01:00:00Z",
                                "status": "ok",
                                "reason": None,
                            },
                        ],
                    }
                }
            ),
        ),
    )
    test_db.commit()

    body = report_body(compose(scope))

    assert f"{_CURSOR_METER} | monthly · {CURSOR_MODELS_SCOPE} | 0%" in body
    assert f"{_OTHER_METER} | monthly · {CURSOR_OTHER_MODELS_SCOPE} | 90%" in body
