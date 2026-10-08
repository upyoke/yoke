"""Session roster presentation projection tests."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.session_presentation_read import session_presentation
from yoke_core.domain.sessions_list_query import build_sessions_query


def test_roster_keeps_execution_and_observed_presentation_independent():
    # The page's levels are resolved once per project by the roster read and
    # handed in; a row whose project the map does not name renders against
    # the universe entry, and an unknown level renders its name alone.
    result = session_presentation(
        {
            "executor": "claude-code",
            "executor_surface": "claude-cli",
            "execution_level": "primary",
            "presentation_surface": "remote-control",
            "presentation_state": "attached",
            "presentation_mode": "bidirectional",
            "presentation_source": "claude-job-state",
            "presentation_observed_at": "2026-08-28T18:00:00Z",
        },
        levels={},
    )

    assert (result["level_label"], result["level_glyph"]) == ("primary", "")

    assert result["presentation_surface"] == "remote-control"
    assert result["presentation_state"] == "attached"
    assert result["executor_mark"]
    query = build_sessions_query("", windowed=False)
    assert "s.executor_surface" in query
    assert "s.presentation_surface" in query
    assert "s.turn_posture" in query
    assert "s.turn_posture_at" in query


def test_row_without_a_project_entry_reads_the_universe_levels():
    from yoke_contracts.levels import default_levels

    result = session_presentation(
        {"executor": "claude-code", "execution_level": "INTERN", "project_id": 9},
        levels={None: default_levels()},
    )

    assert (result["level_label"], result["level_glyph"]) == ("INTERN", "\U0001f423")


def test_fleet_holder_and_delivery_queries_select_waiting_chronology():
    from yoke_core.domain import steering_fleet_report_holders as holders
    from yoke_core.domain import steering_fleet_report_undelivered as undelivered

    holders_src = Path(holders.__file__).read_text()
    undelivered_src = Path(undelivered.__file__).read_text()
    assert "turn_posture" in holders_src and "turn_posture_at" in holders_src
    assert "turn_posture" in undelivered_src and "turn_posture_at" in undelivered_src
