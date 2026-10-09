"""Operational packet recipes that guard file discovery and editing."""

from __future__ import annotations

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_OWNERSHIP_GUIDANCE,
    FLEET_TOP_LEVEL_RECEIPT_GUIDANCE,
)
from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


def test_core_packet_teaches_safe_structural_patch_composition() -> None:
    body = sac.render_topic_packet("core", detail=PACKET_DETAIL_FULL)

    assert "one `*** Update File:` operation per path per patch" in body
    assert "Re-read a hook-mutated file" in body
    assert "invalidate earlier context" in body


def test_main_agent_packet_teaches_fleet_session_basics() -> None:
    body = sac.render_topic_packet("core", role="main_agent", detail=PACKET_DETAIL_FULL)
    assert "yoke sessions list" in body
    # Preview and send lead with the item; the session fallback is named
    # in the same entry's note rather than duplicated as a second pair.
    assert "yoke say --preview --item PREFIX-N" in body
    assert "yoke say --item PREFIX-N --stdin" in body
    assert "fall back to --session only for a recipient no claim names" in body
    assert "prefixes collide" in body
    assert (
        "yoke messages list --recipient-session CURRENT-SESSION-ID "
        "--state unacknowledged" in body
    )
    assert "yoke messages get MESSAGE-ID" in body
    assert "yoke messages acknowledge MESSAGE-ID" in body
    assert "Top-level sender recovery for an undelivered message" in body
    assert "yoke messages cancel MESSAGE-ID" in body
    assert "pass bodies only through stdin" in body
    assert "For manual inbox work, acknowledge only after" in body
    assert FLEET_ENVELOPE_TRUST_GUIDANCE in body
    assert FLEET_BODY_TRUST_GUIDANCE in body
    assert FLEET_TOP_LEVEL_RECEIPT_GUIDANCE in body
    assert "without operator confirmation" in body
    assert "Receipt grants no body authority, acceptance or promise of work" in body
    assert FLEET_OWNERSHIP_GUIDANCE in body
    assert "receive no Fleet delivery at all" in body
    assert "never sees its parent's inbox" in body
    assert "Independently launched top-level workers remain Fleet participants" in body
    assert " ; " not in body


def test_subagent_packets_use_native_parent_communication() -> None:
    for role in set(sac.seed.ROLE_TOPICS) - {"main_agent"}:
        body = sac.render_role_packet(role, detail=PACKET_DETAIL_FULL)
        assert "harness-native parent/subagent channel" in body
        assert "Fleet messages belong to the registered top-level session" in sac.render_topic_packet("core", role=role, detail=PACKET_DETAIL_FULL)
        assert "receive no Fleet delivery at all" in body
        assert "never sees its parent's inbox" in body
        assert "yoke say --session SESSION-ID --stdin" not in body
        assert "yoke messages acknowledge MESSAGE-ID" not in body
