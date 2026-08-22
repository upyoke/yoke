"""Operator-facing item projections carry public refs and actor labels.

The roster, search, and overview projections are operator-facing reads:
their emitted values must be public ``PREFIX-N`` refs and actor display
labels, never the bare numeric primary key or a raw actor id. Fixture
data forces every identity pair to diverge — the internal id differs
from the project sequence, and the actor label is non-numeric — so an
assertion cannot pass vacuously on coincidentally equal numbers.
"""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import request_for
from yoke_core.domain.actors import (
    DISPLAY_LABEL_SURFACE,
    seed_human_actor,
    set_actor_label,
)
from yoke_core.domain.handlers import (
    item_page_reads,
    items_listing,
    items_search,
)

INTERNAL_ID = 4021
SEQUENCE = 7
OWNER_LABEL = "Ada Operator"


@pytest.fixture()
def diverged_item(test_db):
    """One item whose internal id and project sequence differ."""
    insert_item(
        test_db,
        id=INTERNAL_ID,
        title="Divergent identity",
        project_sequence=SEQUENCE,
    )
    test_db.commit()
    return test_db


@pytest.fixture()
def labeled_owner(test_db):
    """A human actor whose display label shares nothing with its id."""
    actor_id = seed_human_actor(test_db)
    set_actor_label(
        test_db, actor_id, OWNER_LABEL, surface=DISPLAY_LABEL_SURFACE,
    )
    test_db.commit()
    return actor_id


def _find(rows: list[dict], title: str) -> dict:
    return next(row for row in rows if row["title"] == title)


class TestItemsListProjection:
    def test_id_column_renders_public_ref(self, diverged_item):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {})
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Divergent identity")
        assert row["id"] == f"YOK-{SEQUENCE}"

    def test_no_emitted_value_is_the_internal_id(self, diverged_item):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {})
        )
        assert outcome.primary_success
        for row in outcome.result_payload["rows"]:
            assert INTERNAL_ID not in {
                v for v in row.values() if isinstance(v, int)
            }
            assert str(INTERNAL_ID) not in row.values()

    def test_internal_id_requires_explicit_opt_in(self, diverged_item):
        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run", {"fields": ["internal_id", "title"]}
            )
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Divergent identity")
        assert row["internal_id"] == str(INTERNAL_ID)

    def test_owner_and_source_render_actor_labels(
        self, diverged_item, labeled_owner,
    ):
        insert_item(
            diverged_item,
            id=INTERNAL_ID + 1,
            title="Owned thing",
            project_sequence=SEQUENCE + 1,
            owner=str(labeled_owner),
            source=str(labeled_owner),
        )
        diverged_item.commit()
        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "title", "source", "owner"]},
            )
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Owned thing")
        assert row["owner"] == OWNER_LABEL
        assert row["source"] == OWNER_LABEL
        assert str(labeled_owner) not in {
            str(v) for v in row.values()
        }

    def test_legacy_text_source_passes_through(self, diverged_item):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {})
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Divergent identity")
        # The fixture seeds a default human actor ("ben"); a non-numeric
        # stored source is legacy text and passes through untouched.
        assert row["source"] == "ben"
        assert row["id"] == f"YOK-{SEQUENCE}"

    def test_orphan_actor_degrades_cell_not_page(self, diverged_item):
        orphan_id = 999999
        insert_item(
            diverged_item,
            id=INTERNAL_ID + 2,
            title="Orphaned ownership",
            project_sequence=SEQUENCE + 2,
            owner=str(orphan_id),
            source=str(orphan_id),
        )
        diverged_item.commit()
        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "title", "source", "owner"]},
            )
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Orphaned ownership")
        assert row["owner"] == ""
        assert row["source"] == ""

    def test_unset_sentinels_render_empty(self, diverged_item):
        insert_item(
            diverged_item,
            id=INTERNAL_ID + 3,
            title="Sentinel owner",
            project_sequence=SEQUENCE + 3,
            owner="None",
            source="null",
        )
        diverged_item.commit()
        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "title", "source", "owner"]},
            )
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Sentinel owner")
        assert row["owner"] == ""
        assert row["source"] == ""

    def test_duplicate_requested_fields_are_rejected(self, diverged_item):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"fields": ["id", "id"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "duplicate" in outcome.error.message


class TestItemsSearchProjection:
    def test_id_key_renders_public_ref_with_numeric_opt_in(
        self, diverged_item,
    ):
        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "Divergent"})
        )
        assert outcome.primary_success
        match = outcome.result_payload["matches"][0]
        assert match["id"] == f"YOK-{SEQUENCE}"
        assert match["internal_id"] == INTERNAL_ID
        assert "public_ref" not in match


class TestItemsOverviewProjection:
    def test_overview_rows_carry_refs_labels_and_numeric_mirror(
        self, diverged_item, labeled_owner,
    ):
        diverged_item.execute(
            "UPDATE items SET owner = %s WHERE id = %s",
            (str(labeled_owner), INTERNAL_ID),
        )
        diverged_item.commit()
        outcome = item_page_reads.handle_items_overview_list(
            request_for("items.overview.list", {})
        )
        assert outcome.primary_success
        row = _find(outcome.result_payload["rows"], "Divergent identity")
        assert row["id"] == f"YOK-{SEQUENCE}"
        assert row["public_ref"] == f"YOK-{SEQUENCE}"
        assert row["internal_id"] == str(INTERNAL_ID)
        assert row["owner"] == OWNER_LABEL
        assert str(labeled_owner) not in {
            str(v) for v in row.values()
        }


class TestDefaultProjectionSingleSource:
    def test_csv_derives_from_domain_tuple(self):
        from yoke_core.api.service_client_items_parsing import (
            _QI_DEFAULT_FIELDS,
        )
        from yoke_core.domain.items_projection import (
            DEFAULT_LIST_FIELDS,
            DEFAULT_LIST_FIELDS_CSV,
        )

        assert _QI_DEFAULT_FIELDS == DEFAULT_LIST_FIELDS_CSV
        assert tuple(_QI_DEFAULT_FIELDS.split(",")) == DEFAULT_LIST_FIELDS
