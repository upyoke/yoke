"""The board draws VISION for the checkout project and refuses a server without vision ownership."""

from __future__ import annotations

import pytest
from yoke_contracts.board.art import ArtConfig
from yoke_contracts.board.config import BoardConfig
from yoke_core.board.renderer import render_board_from_payload
from yoke_core.domain.handlers import orchestration

from runtime.api.board.tests.test_board_data_function import (  # noqa: F401
    _request,
)


def test_client_refuses_vision_replay_from_a_server_without_vision_owner(
    populated_db,
):
    from yoke_contracts.board.data import BoardDataError

    outcome = orchestration.handle_board_data_get(
        _request(
            {
                "scope": "all",
                "config_values": {"timeline_widget": "always"},
                "zen_vision_count": 1,
            }
        )
    )
    payload = dict(outcome.result_payload)
    del payload["vision_project"]

    with pytest.raises(BoardDataError, match="board_data_vision_owner_unavailable"):
        render_board_from_payload(
            payload,
            scope="all",
            config=BoardConfig(),
            art_config=ArtConfig(),
            vision_entries=[("vision", "")],
        )
