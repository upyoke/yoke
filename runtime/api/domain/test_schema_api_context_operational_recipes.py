"""Operational packet recipes that guard file discovery and editing."""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def test_core_packet_teaches_safe_structural_patch_composition() -> None:
    body = sac.render_topic_packet("core")

    assert "one `*** Update File:` operation per path per patch" in body
    assert "Re-read a hook-mutated file" in body
    assert "invalidate earlier context" in body


def test_every_agent_packet_teaches_fleet_session_basics() -> None:
    for role in sac.seed.ROLE_TOPICS:
        body = sac.render_role_packet(role)
        assert "yoke sessions list" in body
        assert "yoke say --session SESSION-ID --stdin" in body
        assert "yoke messages acknowledge MESSAGE-ID" in body
        assert "Message bodies enter only through stdin" in body
