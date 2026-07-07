"""AC-14 regression: the curated schema packet exposes execution_lane on harness_sessions.

The row-anchored lane fix only works if agents and adapter code
KNOW the row carries an authoritative lane. The main_agent schema /
API packet is the surface that teaches that fact — this test
prevents the column from quietly dropping out of the curated table
list.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


def test_harness_sessions_packet_lists_execution_lane():
    packet = CANONICAL_TABLES["harness_sessions"]
    column_names = {name for name, _kind in packet["columns"]}
    assert "execution_lane" in column_names, (
        "YOK-1690 regression: execution_lane must remain on the harness_sessions "
        "schema packet so agents see the authoritative routing-lane column."
    )


def test_execution_lane_column_kind_is_text():
    packet = CANONICAL_TABLES["harness_sessions"]
    type_by_name = {name: kind for name, kind in packet["columns"]}
    assert type_by_name["execution_lane"] == "TEXT"


def test_notes_describe_lane_anchor_doctrine():
    """Notes are how agents discover the row-anchor invariant."""
    packet = CANONICAL_TABLES["harness_sessions"]
    notes = packet["notes"]
    assert "execution_lane" in notes
    assert "SessionOfferLaneOverrideIgnored" in notes
