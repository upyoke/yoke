"""Operational packet recipes that guard file discovery and editing."""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def test_core_packet_teaches_safe_structural_patch_composition() -> None:
    body = sac.render_topic_packet("core")

    assert "one `*** Update File:` operation per path per patch" in body
    assert "Re-read a hook-mutated file" in body
    assert "invalidate earlier context" in body


def test_main_agent_packet_teaches_fleet_session_basics() -> None:
    body = sac.render_role_packet("main_agent")
    assert "yoke sessions list" in body
    assert "yoke say --preview --session SESSION-ID" in body
    assert "yoke say --session SESSION-ID --stdin" in body
    assert (
        "yoke messages list --recipient-session CURRENT-SESSION-ID --state injected"
        in body
    )
    assert "yoke messages get MESSAGE-ID" in body
    assert "yoke messages acknowledge MESSAGE-ID" in body
    assert "pass bodies only through stdin" in body
    assert "Acknowledge only after `yoke messages get` confirms" in body
    assert "This top-level session alone sends and acknowledges Fleet messages" in body
    assert "Forward relevant content to in-process subagents" in body
    assert "they reply there and never send or acknowledge Fleet messages" in body
    assert "Independently launched top-level workers remain Fleet participants" in body
    assert " ; " not in body


def test_subagent_packets_use_native_parent_communication() -> None:
    for role in set(sac.seed.ROLE_TOPICS) - {"main_agent"}:
        body = sac.render_role_packet(role)
        assert "harness-native parent/subagent channel" in body
        assert "Fleet messages belong to the registered top-level session" in body
        assert "yoke say --session SESSION-ID --stdin" not in body
        assert "yoke messages acknowledge MESSAGE-ID" not in body
