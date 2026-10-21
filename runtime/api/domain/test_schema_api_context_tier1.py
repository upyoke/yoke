"""Tier 1 packet expansion — column-listing regressions.

Sibling of :mod:`test_schema_api_context` and
:mod:`test_schema_api_context_topics`. Column names appear adjacent to
their owning tables in ``main_agent``'s rendered packet, and the
JSON-nested and newer ``harness_sessions`` columns are enumerated.
"""

from __future__ import annotations

import re

from runtime.api.domain.schema_api_context_packet_test_support import (
    JSON_NESTED_COLUMNS_REQUIRED,
    NEW_HARNESS_SESSION_COLUMNS,
    main_body,
)


# ---------------------------------------------------------------------------
# Column-name salience + JSON schemas
# ---------------------------------------------------------------------------


def test_current_item_id_appears_adjacent_to_harness_sessions() -> None:
    body = main_body()
    # The salient harness_sessions bullet must enumerate
    # current_item_id in the column list; the rendered bullet is a
    # single contiguous region.
    pat = re.compile(r"`harness_sessions`.*?current_item_id", re.DOTALL)
    assert pat.search(body), (
        "current_item_id must appear adjacent to its owning table "
        "harness_sessions in the schema cheat sheet."
    )


def test_path_string_appears_adjacent_to_path_targets() -> None:
    body = main_body()
    pat = re.compile(r"`path_targets`.*?path_string", re.DOTALL)
    assert pat.search(body), (
        "path_string must appear adjacent to its owning table "
        "path_targets in the schema cheat sheet."
    )


def test_claim_id_appears_adjacent_to_path_claim_targets() -> None:
    body = main_body()
    pat = re.compile(r"`path_claim_targets`.*?claim_id", re.DOTALL)
    assert pat.search(body), (
        "claim_id must appear adjacent to its owning table "
        "path_claim_targets in the schema cheat sheet."
    )


def test_section_name_appears_adjacent_to_item_sections() -> None:
    body = main_body()
    pat = re.compile(r"`item_sections`.*?section_name", re.DOTALL)
    assert pat.search(body), (
        "section_name must appear adjacent to its owning table "
        "item_sections in the schema cheat sheet."
    )


def test_json_nested_field_schemas_appear_for_enumerated_columns() -> None:
    body = main_body()
    for column in JSON_NESTED_COLUMNS_REQUIRED:
        assert column in body, (
            f"JSON-nested-field schema for {column} must appear in the "
            "rendered main_agent packet."
        )


# ---------------------------------------------------------------------------
# harness_sessions: new columns surface
# ---------------------------------------------------------------------------


def test_new_harness_sessions_columns_present() -> None:
    body = main_body()
    for column in NEW_HARNESS_SESSION_COLUMNS:
        assert column in body, (
            f"harness_sessions.{column} must be enumerated in the "
            "schema cheat sheet (task 002 packet expansion)."
        )
