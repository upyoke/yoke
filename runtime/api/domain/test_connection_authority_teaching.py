"""Connection-authority teaching is capability-shaped, not prohibition-only."""

from __future__ import annotations

from yoke_contracts.connection_authority_teaching import (
    CONNECTION_AUTHORITY_STANZA,
    DB_GROUP_TEACHING,
    ENV_LIST_AUTHORITY_FOOTER,
)
from yoke_core.domain.main_agent_packet import (
    render_main_agent_block,
    render_main_agent_section,
)


def test_teaching_names_the_capability_alongside_the_restriction() -> None:
    for text in (DB_GROUP_TEACHING, ENV_LIST_AUTHORITY_FOOTER):
        assert "yoke_core.cli.db_router query" in text
        assert "db-admin" in text
        assert "read-only" in text or "stays read-only" in text
        assert "source-dev" in text
    assert "yoke env list" in CONNECTION_AUTHORITY_STANZA
    assert "*-db-admin" in CONNECTION_AUTHORITY_STANZA
    assert "yoke db` `--help" in CONNECTION_AUTHORITY_STANZA
    assert "yoke_core.cli.db_router" not in CONNECTION_AUTHORITY_STANZA


def test_session_packet_names_reachable_connection_kinds() -> None:
    block = render_main_agent_block()
    assert CONNECTION_AUTHORITY_STANZA in block
    assert "yoke env list" in block
    section = render_main_agent_section()
    assert CONNECTION_AUTHORITY_STANZA in section
