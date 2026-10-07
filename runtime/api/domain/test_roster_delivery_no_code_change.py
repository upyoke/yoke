"""A card's delivery box says "no code change" only from the item's own record.

An item whose work changed no code lands no merge, and a missing merge is
also what unfinished work looks like. The card can tell them apart only from
the execution evidence that attests the no-change outcome.
"""

from __future__ import annotations

from runtime.api.domain.test_roster_delivery_shared_reads import FLOW, _version_id
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.item_json_sections import upsert_json_section
from yoke_core.domain.item_overview_read import enrich_item_overview_rows


def test_recorded_no_change_evidence_reaches_the_card_as_its_delivery_fact() -> None:
    """Only the item whose evidence attests no change says so; absence does not."""
    with test_database() as conn:
        rows = []
        for item_id in (8400, 8401):
            insert_item(
                conn,
                id=item_id,
                title="no landing",
                status="release",
                deployment_flow=FLOW,
            )
            rows.append(
                {
                    "internal_id": item_id,
                    "id": item_id,
                    "status": "release",
                    "workflow_version_id": _version_id(conn, item_id),
                    "deployment_flow": FLOW,
                }
            )
        upsert_json_section(
            conn,
            item_id=8400,
            section=DASH_EVIDENCE_SECTION,
            payload={"no_changes": True, "touched_files": []},
            ordering=900,
        )
        conn.commit()
        enriched = enrich_item_overview_rows(rows)

    by_id = {row["internal_id"]: row["delivery"] for row in enriched}
    assert by_id[8400]["no_code_change"] is True
    assert by_id[8401]["no_code_change"] is False
