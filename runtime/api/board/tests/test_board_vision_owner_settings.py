"""A board request without a settings project names no vision owner."""

from __future__ import annotations

from yoke_core.domain.handlers import orchestration

from runtime.api.board.tests.test_board_data_function import (  # noqa: F401
    _request,
)


def test_handler_without_settings_project_draws_no_vision(populated_db):
    outcome = orchestration.handle_board_data_get(
        _request(
            {
                "scope": "all",
                "config_values": {"timeline_widget": "always"},
                "zen_vision_count": 3,
            }
        )
    )

    assert outcome.primary_success
    assert outcome.result_payload["vision_project"] is None
