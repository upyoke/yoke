"""A launch is ranked by the meter the model it names actually bills to."""

from __future__ import annotations

from yoke_core.domain.session_launch_placement import surface_headroom
from yoke_core.domain.session_launch_surface_readings import (
    unrequested_surface_readings,
)
from yoke_core.domain.session_launch_surface_selection import preview_launch

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


def _relay(conn, *, cursor_models: float, other_models: float) -> None:
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        surface=CURSOR_SURFACE,
        version=CURSOR_VERSION,
        plan_limits=_cursor_pools(cursor_models, other_models),
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
    _relay(conn, cursor_models=0.0, other_models=90.0)

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
    }


def test_readings_drop_the_surface_the_caller_asked_for() -> None:
    """The requested surface is already ranked; these rows are the rest."""
    readings = unrequested_surface_readings(
        {
            ("m1", CURSOR_SURFACE): (12.0, "weekly plan"),
            ("m1", "claude-cli"): (125.0, "weekly plan"),
        },
        requested_surface=CURSOR_SURFACE,
    )

    assert [reading.surface for reading in readings] == ["claude-cli"]
    assert readings[0].headroom_percent == 125.0
    assert readings[0].headroom_window == "weekly plan"


def test_readings_put_the_roomiest_surface_first() -> None:
    """The only question these rows answer is whether somewhere had more room."""
    readings = unrequested_surface_readings(
        {
            ("m1", "claude-cli"): (40.0, "weekly plan"),
            ("m1", "codex-cli"): (125.0, "weekly plan"),
            ("m2", "codex-cli"): (80.0, "weekly plan"),
        },
        requested_surface=CURSOR_SURFACE,
    )

    assert [reading.headroom_percent for reading in readings] == [125.0, 80.0, 40.0]


def test_a_preview_names_the_surfaces_it_was_not_asked_about() -> None:
    """Placement ranks within a surface, so the act has to carry the rest."""
    conn = launch_connection()
    _relay(conn, cursor_models=62.0, other_models=3.0)

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=CURSOR_SURFACE,
        now=NOW,
    )

    assert CURSOR_SURFACE not in {
        reading.surface for reading in preview.unrequested_surface_headroom
    }
    assert "unrequested_surface_headroom" in preview.to_dict()
