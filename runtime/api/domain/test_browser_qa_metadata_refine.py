"""Refine-path correction coverage for browser_qa_metadata.

Covers the /yoke refine rubric dimension: misclassified metadata from
/yoke idea must be correctable through the sanctioned structured-field
write surface, under the additive-only discipline refine applies to every
other structured field.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import apply_fixture_schema_ddl, init_test_db
from yoke_core.domain.browser_qa_metadata import (
    BrowserQaMetadataError,
    NEGATIVE_DEFAULT,
    canonical_json,
    negative_default,
    validate_json_string,
)
from yoke_core.domain.items import (
    insert_item,
    query_item,
    update_structured_field,
)


@pytest.fixture
def db_with_idea_item(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        insert_item(
            item_id=42,
            title="Refine dimension smoke test",
            item_type="issue",
            status="idea",
            priority="medium",
            source="user",
            project="yoke",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            db_path=path,
        )
        yield path


def _seed_metadata(db_path, payload):
    update_structured_field(
        42, "browser_qa_metadata", canonical_json(payload),
        source="idea", db_path=db_path,
    )


class TestRefineCanCorrectMisclassifiedMetadata:
    """Refine corrects the wrong-browser-classification case."""

    def test_idea_marked_not_browser_but_refine_corrects_to_browser(
        self, db_with_idea_item,
    ):
        # /yoke idea undercounted the item as non-browser
        _seed_metadata(db_with_idea_item, NEGATIVE_DEFAULT)
        assert (
            query_item(42, "browser_qa_metadata", db_path=db_with_idea_item)
            == canonical_json(NEGATIVE_DEFAULT)
        )

        # Refine re-reads the spec, discovers a UI surface, writes a correction
        corrected = {
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [2000],
        }
        update_structured_field(
            42, "browser_qa_metadata", canonical_json(corrected),
            source="refine", db_path=db_with_idea_item,
        )

        stored = query_item(42, "browser_qa_metadata", db_path=db_with_idea_item)
        assert json.loads(stored) == corrected

    def test_refine_can_extend_routes_additively(self, db_with_idea_item):
        # Idea recorded one route
        initial = {
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [],
        }
        _seed_metadata(db_with_idea_item, initial)

        # Refine discovers the spec references /forgot-password too
        existing = json.loads(
            query_item(42, "browser_qa_metadata", db_path=db_with_idea_item)
        )
        enhanced = negative_default()
        enhanced.update(existing)
        enhanced["browser_routes"] = sorted(
            set(existing["browser_routes"]) | {"/forgot-password"}
        )
        update_structured_field(
            42, "browser_qa_metadata", canonical_json(enhanced),
            source="refine", db_path=db_with_idea_item,
        )

        stored = json.loads(
            query_item(42, "browser_qa_metadata", db_path=db_with_idea_item)
        )
        assert stored["browser_routes"] == ["/forgot-password", "/login"]
        assert stored["browser_testable"] is True

    def test_refine_correction_with_invalid_json_is_rejected(
        self, db_with_idea_item,
    ):
        _seed_metadata(db_with_idea_item, NEGATIVE_DEFAULT)

        with pytest.raises(BrowserQaMetadataError, match="malformed JSON"):
            update_structured_field(
                42, "browser_qa_metadata", "{ this is not json",
                source="refine", db_path=db_with_idea_item,
            )

        # Original metadata preserved — the validator blocks before the write
        stored = query_item(
            42, "browser_qa_metadata", db_path=db_with_idea_item,
        )
        assert json.loads(stored) == NEGATIVE_DEFAULT

    def test_refine_correction_with_contradiction_is_rejected(
        self, db_with_idea_item,
    ):
        _seed_metadata(db_with_idea_item, NEGATIVE_DEFAULT)

        contradictory = json.dumps({
            "browser_testable": False,
            "visual_outcome": True,
            "browser_routes": [],
            "browser_timing_hints_ms": [],
        })
        with pytest.raises(BrowserQaMetadataError, match="contradicts"):
            update_structured_field(
                42, "browser_qa_metadata", contradictory,
                source="refine", db_path=db_with_idea_item,
            )
        stored = query_item(
            42, "browser_qa_metadata", db_path=db_with_idea_item,
        )
        assert json.loads(stored) == NEGATIVE_DEFAULT

    def test_refine_correction_rejects_whitespace_in_route(
        self, db_with_idea_item,
    ):
        _seed_metadata(db_with_idea_item, NEGATIVE_DEFAULT)

        payload = json.dumps({
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/forgot password"],
            "browser_timing_hints_ms": [],
        })
        with pytest.raises(BrowserQaMetadataError, match="whitespace"):
            update_structured_field(
                42, "browser_qa_metadata", payload,
                source="refine", db_path=db_with_idea_item,
            )

    def test_refine_correction_rejects_out_of_range_timing(
        self, db_with_idea_item,
    ):
        _seed_metadata(db_with_idea_item, NEGATIVE_DEFAULT)

        payload = json.dumps({
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [999_999],
        })
        with pytest.raises(BrowserQaMetadataError, match="exceeds"):
            update_structured_field(
                42, "browser_qa_metadata", payload,
                source="refine", db_path=db_with_idea_item,
            )


class TestRefineCorrectionValidatorHelpers:
    """Refine drives validate_json_string directly when previewing corrections."""

    def test_validator_round_trips_canonical_form(self):
        raw = json.dumps({
            "browser_timing_hints_ms": [7000, 2000],
            "browser_routes": ["/Login"],
            "visual_outcome": True,
            "browser_testable": True,
        })
        canonical = validate_json_string(raw)
        decoded = json.loads(canonical)
        assert decoded["browser_routes"] == ["/login"]
        assert decoded["browser_timing_hints_ms"] == [2000, 7000]
