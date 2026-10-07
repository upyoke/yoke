"""Product connection teaching names reachable commands and escalation."""

from __future__ import annotations

from yoke_contracts.connection_authority_teaching import (
    CONNECTION_AUTHORITY_STANZA,
    DB_GROUP_TEACHING,
    ENV_LIST_AUTHORITY_FOOTER,
)
from yoke_core.domain.main_agent_packet import render_main_agent_block


def test_product_teaching_escalates_missing_mutations() -> None:
    for text in (
        DB_GROUP_TEACHING,
        ENV_LIST_AUTHORITY_FOOTER,
        CONNECTION_AUTHORITY_STANZA,
    ):
        assert "db-admin" not in text
        assert "db_router query" not in text
        assert "read-only" in text or "stays read-only" in text
        assert "escalate" in text.lower()
        assert "control-plane operator" in text
    assert "yoke env list" in CONNECTION_AUTHORITY_STANZA


def test_session_packet_names_reachable_connection_kinds() -> None:
    block = render_main_agent_block()
    assert CONNECTION_AUTHORITY_STANZA in block
    assert "yoke env list" in block
    assert "db-admin" not in block
