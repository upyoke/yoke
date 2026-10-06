"""Regression: the curated schema packet exposes execution_level on harness_sessions.

Agents and adapter code need the row's identity and roster level. The
main_agent schema / API packet is the surface that teaches that fact
— this test prevents the column from quietly dropping out of the
curated table list.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


def test_harness_sessions_packet_lists_execution_level():
    packet = CANONICAL_TABLES["harness_sessions"]
    column_names = {name for name, _kind in packet["columns"]}
    assert "execution_level" in column_names, (
        "execution_level must remain on the harness_sessions "
        "schema packet so agents see the identity and roster column."
    )


def test_execution_level_column_kind_is_text():
    packet = CANONICAL_TABLES["harness_sessions"]
    type_by_name = {name: kind for name, kind in packet["columns"]}
    assert type_by_name["execution_level"] == "TEXT"


def test_notes_describe_level_identity_and_roster_role():
    packet = CANONICAL_TABLES["harness_sessions"]
    notes = packet["notes"]
    assert "execution_level" in notes
    assert "groups sessions in identity and roster views" in notes


def test_notes_name_registered_identity_read():
    notes = CANONICAL_TABLES["harness_sessions"]["notes"]
    assert "yoke sessions identity" in notes
