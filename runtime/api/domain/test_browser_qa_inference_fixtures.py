"""Fixture-driven regression tests for browser_qa_metadata inference and persistence.

Each fixture in ``runtime/api/domain/test_data/browser_qa_inference/`` captures
a representative ticket body alongside the metadata the idea skill's agentic
inference is expected to produce. The LLM itself is not tested here — these
fixtures serve two concrete jobs:

1. Documentation: the expected_metadata for each fixture is the canonical
   "what good inference looks like" for that class of ticket. Drift between
   skill prompts and fixtures is an operator-visible signal.
2. Persistence round-trip coverage: every fixture's expected_metadata is
   round-tripped through the validator and the structured-write path so the
   schema stays connected to real-world shapes, and so invalid fixture data
   is caught during CI rather than at runtime.

Fixture matrix covers AC-30 categories: pure-UI, pure-backend, mixed,
compound-page-name-in-prose, route-words-in-non-URL-context.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import apply_fixture_schema_ddl, init_test_db
from yoke_core.domain.browser_qa_metadata import (
    NEGATIVE_DEFAULT,
    canonical_json,
    validate,
    validate_json_string,
)
from yoke_core.domain.items import insert_item, query_item, update_structured_field


FIXTURE_DIR = Path(__file__).parent / "test_data" / "browser_qa_inference"

REQUIRED_LABELS = frozenset({
    "pure-UI",
    "pure-backend",
    "mixed",
    "compound-page-name-in-prose",
    "route-words-in-non-URL-context",
})


def _load_fixtures():
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        fixtures.append((path.name, data))
    return fixtures


FIXTURES = _load_fixtures()


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        yield path


class TestFixtureCoverage:
    """The fixture directory must exercise every AC-30 category."""

    def test_fixture_directory_exists(self):
        assert FIXTURE_DIR.is_dir(), f"Missing fixture dir: {FIXTURE_DIR}"

    def test_all_categories_covered(self):
        labels = {data["label"] for _, data in FIXTURES}
        missing = REQUIRED_LABELS - labels
        assert not missing, f"Missing category coverage: {sorted(missing)}"


@pytest.mark.parametrize("filename,fixture", FIXTURES,
                         ids=[f for f, _ in FIXTURES])
class TestFixtureShape:
    def test_fixture_has_required_keys(self, filename, fixture):
        for key in ("label", "title", "body", "expected_metadata"):
            assert key in fixture, f"{filename}: missing key {key!r}"

    def test_fixture_body_is_title_inclusive(self, filename, fixture):
        """The fixture body must begin with a level-1 heading that matches title."""
        first_line = fixture["body"].splitlines()[0]
        assert first_line.startswith("# "), (
            f"{filename}: body must lead with a level-1 heading"
        )

    def test_expected_metadata_validates(self, filename, fixture):
        # Idempotent — validate() returns the normalized form, which must
        # equal the fixture's expected metadata (fixtures are authored in
        # canonical form so drift is noisy).
        normalized = validate(fixture["expected_metadata"])
        assert normalized == fixture["expected_metadata"]

    def test_canonical_json_round_trip(self, filename, fixture):
        raw = canonical_json(fixture["expected_metadata"])
        assert json.loads(raw) == fixture["expected_metadata"]
        assert validate_json_string(raw) == raw


@pytest.mark.parametrize("filename,fixture", FIXTURES,
                         ids=[f for f, _ in FIXTURES])
class TestFixturePersistence:
    """Every fixture round-trips through the structured-field write path."""

    def test_structured_write_and_read_back(self, filename, fixture, db_path):
        insert_item(
            item_id=1,
            title=fixture["title"],
            item_type="issue",
            status="idea",
            priority="medium",
            source="user",
            project="yoke",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            db_path=db_path,
        )
        payload = canonical_json(fixture["expected_metadata"])
        update_structured_field(
            1, "browser_qa_metadata", payload,
            source="idea", db_path=db_path,
        )
        stored = query_item(1, "browser_qa_metadata", db_path=db_path)
        assert stored == payload
        assert json.loads(stored) == fixture["expected_metadata"]


class TestNonBrowserFixturesAreNegativeDefault:
    """Non-browser fixtures record the explicit negative object, not NULL."""

    def test_pure_backend_matches_negative_default(self):
        fixture = {
            data["label"]: data for _, data in FIXTURES
        }["pure-backend"]
        assert fixture["expected_metadata"] == NEGATIVE_DEFAULT

    def test_route_words_in_non_url_matches_negative_default(self):
        fixture = {
            data["label"]: data for _, data in FIXTURES
        }["route-words-in-non-URL-context"]
        assert fixture["expected_metadata"] == NEGATIVE_DEFAULT
