"""A launch is ranked by the meter the model it names actually bills to."""

from __future__ import annotations

from yoke_contracts.session_control.extra_usage import EXTRA_AVAILABLE, extra_usage
from yoke_contracts.session_control.model_billing_pools import EXTRA_USAGE_PERMITS
from yoke_core.domain.session_launch_placement import surface_headroom
from yoke_core.domain.session_launch_surface_selection import preview_launch

from runtime.api.domain.session_launch_level_test_support import EXTRA_OFF
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


FAR_RESET = "2026-08-22T17:00:00Z"
#: Both machines are shared capacity, so placement is decided by the readings
#: rather than by who may use them at all.
SHARED_ACCESS = {"use": {"mode": "universe"}}
#: Cursor publishes two included pools at once, and a model bills to exactly
#: one of them.
CURSOR_SURFACE = "cursor-cli"
CURSOR_VERSION = "2026.08.11"
CURSOR_POOL_MODEL = "cursor-grok-4.6-high"
OTHER_POOL_MODEL = "claude-opus-5"


def _cursor_pools(cursor_models: float, other_models: float) -> dict:
    return {
        CURSOR_SURFACE: {
            "plan_tier": "pro",
            "windows": [
                {
                    "window_kind": "monthly",
                    "scope": "Cursor Models",
                    "remaining_percent": cursor_models,
                    "resets_at": FAR_RESET,
                    "status": "ok",
                },
                {
                    "window_kind": "monthly",
                    "scope": "Other Models",
                    "remaining_percent": other_models,
                    "resets_at": FAR_RESET,
                    "status": "ok",
                },
            ],
        }
    }


def _relay(conn, *, cursor_models: float, other_models: float, extra=None) -> None:
    plan_limits = _cursor_pools(cursor_models, other_models)
    if extra is not None:
        plan_limits[CURSOR_SURFACE].update(observed_at=NOW, extra_usage=extra)
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        surface=CURSOR_SURFACE,
        version=CURSOR_VERSION,
        plan_limits=plan_limits,
        access=SHARED_ACCESS,
    )


def test_headroom_reports_the_pool_the_named_model_actually_bills_to() -> None:
    """The lower pool must not answer for a model that never draws on it."""
    conn = launch_connection()
    _relay(conn, cursor_models=62.0, other_models=3.0)

    readings = surface_headroom(conn, project_id=10, now=NOW, model=CURSOR_POOL_MODEL)

    _headroom, window = readings[("machine-a", CURSOR_SURFACE)]
    assert window == "monthly \u00b7 Cursor Models"


def test_a_model_on_the_other_pool_is_ranked_by_that_pool() -> None:
    conn = launch_connection()
    _relay(conn, cursor_models=62.0, other_models=3.0)

    readings = surface_headroom(conn, project_id=10, now=NOW, model=OTHER_POOL_MODEL)

    _headroom, window = readings[("machine-a", CURSOR_SURFACE)]
    assert window == "monthly \u00b7 Other Models"


def test_naming_no_model_still_reports_the_soonest_wall() -> None:
    conn = launch_connection()
    _relay(conn, cursor_models=62.0, other_models=3.0)

    readings = surface_headroom(conn, project_id=10, now=NOW)

    _headroom, window = readings[("machine-a", CURSOR_SURFACE)]
    assert window == "monthly \u00b7 Other Models"


def test_a_candidate_carries_its_requested_model_pool_reading() -> None:
    conn = launch_connection()
    _relay(conn, cursor_models=0.0, other_models=90.0, extra=EXTRA_OFF)

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=CURSOR_SURFACE,
        now=NOW,
        model=CURSOR_POOL_MODEL,
    )

    candidate = preview.machine_candidates[0]
    assert candidate.model_pool == {
        "pool": "Cursor Models",
        "remaining_percent": 0.0,
        "exhausted": True,
        "reason": None,
        "included_empty": True,
        "extra_status": "disabled",
        "extra_label": "extra usage disabled (user_disabled)",
    }


def test_an_empty_pool_with_usage_based_pricing_on_is_not_exhausted() -> None:
    conn = launch_connection()
    on = extra_usage(EXTRA_AVAILABLE, meter="GetHardLimit.noUsageBasedAllowed")
    _relay(conn, cursor_models=0.0, other_models=90.0, extra=on)

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=CURSOR_SURFACE,
        now=NOW,
        model=CURSOR_POOL_MODEL,
    )

    pool = preview.machine_candidates[0].model_pool
    assert (pool["exhausted"], pool["included_empty"]) == (False, True)
    assert pool["reason"] == EXTRA_USAGE_PERMITS
