"""Regression: the curated schema packet exposes execution_lane on harness_sessions.

Agents and adapter code need the row's default routing lane. The
main_agent schema / API packet is the surface that teaches that fact
— this test prevents the column from quietly dropping out of the
curated table list.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


def test_harness_sessions_packet_lists_execution_lane():
    packet = CANONICAL_TABLES["harness_sessions"]
    column_names = {name for name, _kind in packet["columns"]}
    assert "execution_lane" in column_names, (
        "execution_lane must remain on the harness_sessions "
        "schema packet so agents see the default routing-lane column."
    )


def test_execution_lane_column_kind_is_text():
    packet = CANONICAL_TABLES["harness_sessions"]
    type_by_name = {name: kind for name, kind in packet["columns"]}
    assert type_by_name["execution_lane"] == "TEXT"


def test_notes_describe_lane_override_doctrine():
    """Notes are how agents discover the row-default / caller-override rule."""
    packet = CANONICAL_TABLES["harness_sessions"]
    notes = packet["notes"]
    assert "execution_lane" in notes
    assert "SessionOfferLaneOverrideApplied" in notes
