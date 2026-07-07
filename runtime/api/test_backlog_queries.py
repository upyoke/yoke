"""Query and small mutation tests for ``yoke_core.domain.backlog``.

Covers:
  - get_next_display_id (next ID helper)
  - dedup_search (title/spec fuzzy-match search)
  - TestExecuteBatchUpdate (batch field update across multiple items)
  - TestCLI (CLI entry-point argument validation)

Close-path dependency reconciliation lives in
``test_backlog_queries_dependency.py``; structured-write tests live in
``test_backlog_queries_structured.py``; frozen-attestation immutability
lives in ``test_backlog_queries_freeze.py``.

Shared fixtures and seed helpers are imported from ``test_backlog``.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from yoke_core.domain import backlog
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)


# ---------------------------------------------------------------------------
# next ID / dedup search
# ---------------------------------------------------------------------------


class TestNextDisplayId:
    def test_returns_display_id(self, tmp_db):
        _seed_item(tmp_db, id=1)
        _seed_item(tmp_db, id=2)

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            assert backlog.get_next_display_id() == "YOK-3"


class TestDedupSearch:
    def test_matches_title_and_spec(self, tmp_db):
        _seed_item(tmp_db, id=1, title="Unique widget feature", spec="# Body\nfrobnicator mention\n")
        _seed_item(tmp_db, id=2, title="Another item", spec="# Body\nnothing relevant\n")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            title_matches = backlog.dedup_search("widget")
            body_matches = backlog.dedup_search("frobnicator")

        assert title_matches == [
            {"id": 1, "title": "Unique widget feature", "status": "idea"}
        ]
        assert body_matches == [
            {"id": 1, "title": "Unique widget feature", "status": "idea"}
        ]

    def test_returns_empty_when_no_match(self, tmp_db):
        _seed_item(tmp_db, id=1, title="Alpha", spec="# Body\nbeta\n")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            matches = backlog.dedup_search("zzzznonexistent")

        assert matches == []


# ---------------------------------------------------------------------------
# batch update
# ---------------------------------------------------------------------------


class TestExecuteBatchUpdate:
    def test_batch_update_applies_field_across_items(self, tmp_db):
        _seed_item(tmp_db, id=1, frozen=0)
        _seed_item(tmp_db, id=2, frozen=0)
        out = io.StringIO()

        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_batch_update(
                item_ids=[1, 2],
                field="frozen",
                value="true",
                out=out,
            )

        assert result["success"] is True
        assert result["updated_count"] == 2
        assert _item_field(tmp_db, 1, "frozen") == 1
        assert _item_field(tmp_db, 2, "frozen") == 1
        assert "Batch updated 2 item(s): frozen → true" in out.getvalue()
        patched["_rebuild_board"].assert_called_once_with(out)

    def test_batch_update_stops_on_first_failure(self, tmp_db):
        _seed_item(tmp_db, id=1, status="idea")
        _seed_item(tmp_db, id=2, status="idea")
        out = io.StringIO()

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_batch_update(
                item_ids=[1, 2],
                field="status",
                value="definitely-not-a-status",
                out=out,
            )

        assert result["success"] is False
        assert result["updated_count"] == 0
        assert _item_field(tmp_db, 1, "status") == "idea"
        assert _item_field(tmp_db, 2, "status") == "idea"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI:
    def test_no_args(self):
        rc = backlog.main([])
        assert rc == 2

    def test_unknown_command(self):
        rc = backlog.main(["bogus"])
        assert rc == 2

    def test_create_missing_title(self):
        rc = backlog.main(["create"])
        assert rc == 2

    def test_update_missing_args(self):
        rc = backlog.main(["update"])
        assert rc == 2

    def test_structured_write_missing_args(self):
        rc = backlog.main(["structured-write"])
        assert rc == 2
