"""The session packet carries the product connection-authority stanza."""

from __future__ import annotations

from yoke_contracts.connection_authority_teaching import CONNECTION_AUTHORITY_STANZA
from yoke_core.domain.main_agent_packet import render_main_agent_block


def test_session_packet_names_reachable_connection_kinds() -> None:
    block = render_main_agent_block()
    assert CONNECTION_AUTHORITY_STANZA in block
