"""Paged Items roster: filtering, counting, cursor paging, and projection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.api.conftest import insert_item
from runtime.api.item_roster_test_support import (
    iso_minutes_ago as _iso,
    public_refs as _refs,
    read_roster as _roster,
    seed_ladder as _seed_ladder,
)
from yoke_core.domain.actors import (
    seed_human_actor,
    set_actor_name,
)
from yoke_core.domain.handlers import item_page_reads
from yoke_core.domain.item_overview_read import COMPACT_ROSTER_FIELDS
from yoke_core.domain.item_roster_read import (
    RosterCursorError,
    decode_cursor,
    encode_cursor,
)


def test_page_reports_full_match_count_and_next_cursor(test_db):
    _seed_ladder(test_db, 7)
    outcome = _roster(page_size=3)
    assert outcome.primary_success
    result = outcome.result_payload
    assert len(result["rows"]) == 3
    assert result["count"] == 3
    # The count behind the page is the whole match set, not the page length.
    assert result["match_count"] >= 7
    assert result["next_cursor"]


def test_load_more_pages_without_duplicates_or_omissions(test_db):
    _seed_ladder(test_db, 10, first_id=720)
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        outcome = _roster(page_size=3, cursor=cursor) if cursor else _roster(
            page_size=3,
        )
        assert outcome.primary_success
        seen.extend(_refs(outcome))
        cursor = outcome.result_payload["next_cursor"]
        if cursor is None:
            break
    assert cursor is None, "paging never terminated"
    assert len(seen) == len(set(seen)), "a page repeated a row"
    ladder = [ref for ref in seen if ref]
    assert len(ladder) >= 10


def test_final_page_returns_no_cursor(test_db):
    _seed_ladder(test_db, 2, first_id=760)
    outcome = _roster(
        page_size=item_page_reads.MAX_ROSTER_PAGE_SIZE,
        workflow="issue",
        status="implementing",
    )
    assert outcome.primary_success
    assert outcome.result_payload["next_cursor"] is None


def test_paging_is_stable_across_empty_and_unsuffixed_timestamps(test_db):
    """The sort key is coalesced and the cursor is verbatim.

    ``items.updated_at`` is TEXT: it is empty on some rows and on at least one
    row omits the trailing ``Z``. Both shapes must page exactly once.
    """
    insert_item(
        test_db, id=781, title="empty updated", status="implementing",
        created_at=_iso(30), updated_at="",
    )
    insert_item(
        test_db, id=782, title="no zulu suffix", status="implementing",
        created_at=_iso(40),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    insert_item(
        test_db, id=783, title="canonical", status="implementing",
        created_at=_iso(50), updated_at=_iso(20),
    )
    test_db.commit()

    targets = {"empty updated", "no zulu suffix", "canonical"}
    seen: list[str] = []
    cursor = None
    while True:
        outcome = (
            _roster(page_size=1, cursor=cursor)
            if cursor else _roster(page_size=1)
        )
        assert outcome.primary_success
        seen.extend(row["title"] for row in outcome.result_payload["rows"])
        cursor = outcome.result_payload["next_cursor"]
        if cursor is None:
            break
    assert targets <= set(seen)
    for title in targets:
        assert seen.count(title) == 1, f"{title} paged more than once"


def test_search_reaches_history_beyond_the_loaded_page(test_db):
    _seed_ladder(test_db, 5, first_id=800)
    insert_item(
        test_db, id=899, title="a distinctive needle title",
        status="done", created_at=_iso(9000), updated_at=_iso(9000),
    )
    test_db.commit()
    # The needle is the oldest row, so a first page of 1 cannot contain it.
    outcome = _roster(page_size=1, search="distinctive needle")
    assert outcome.primary_success
    titles = [row["title"] for row in outcome.result_payload["rows"]]
    assert titles == ["a distinctive needle title"]
    assert outcome.result_payload["match_count"] == 1


def test_search_matches_public_ref_and_owner_label(test_db):
    actor_id = seed_human_actor(test_db)
    set_actor_name(test_db, actor_id, "Marguerite")
    insert_item(
        test_db, id=901, title="owned row", status="implementing",
        owner=str(actor_id), created_at=_iso(10), updated_at=_iso(10),
    )
    test_db.commit()
    by_owner = _roster(page_size=50, search="marguerite")
    assert by_owner.primary_success
    assert "owned row" in [row["title"] for row in by_owner.result_payload["rows"]]

    ref = by_owner.result_payload["rows"][0]["public_ref"]
    by_ref = _roster(page_size=50, search=ref.lower())
    assert by_ref.primary_success
    assert ref in _refs(by_ref)


def test_filters_run_before_the_page_and_stay_complete(test_db):
    insert_item(
        test_db, id=910, title="planned row", status="planned",
        created_at=_iso(10), updated_at=_iso(10),
    )
    insert_item(
        test_db, id=911, title="implementing row", status="implementing",
        created_at=_iso(11), updated_at=_iso(11),
    )
    test_db.commit()
    outcome = _roster(page_size=1, status="planned")
    assert outcome.primary_success
    assert all(
        row["status"] == "planned" for row in outcome.result_payload["rows"]
    )
    # Choices describe the scope, not the one row this page happened to serve.
    statuses = {
        choice["id"] for choice in outcome.result_payload["filters"]["statuses"]
    }
    assert {"planned", "implementing"} <= statuses
    assert "issue" in outcome.result_payload["filters"]["workflow_ids"]


def test_continuing_a_sequence_does_not_recompute_filter_choices(test_db):
    """A Load more carries no choices: the caller already holds them.

    The cursor cannot change the scope those choices describe, so recomputing
    a scope-wide DISTINCT per page would buy the same answer again.
    """
    _seed_ladder(test_db, 4, first_id=970)
    first = _roster(page_size=2)
    assert first.primary_success
    assert first.result_payload["filters"]["workflow_ids"]

    following = _roster(
        page_size=2, cursor=first.result_payload["next_cursor"],
    )
    assert following.primary_success
    assert following.result_payload["filters"] is None
    # The total behind the page still rides every page, because the heading
    # reports it and the match set can move under a paging sequence.
    assert following.result_payload["match_count"] >= 4


def test_rows_carry_only_rendered_roster_fields(test_db):
    _seed_ladder(test_db, 1, first_id=920)
    outcome = _roster(page_size=5)
    assert outcome.primary_success
    for row in outcome.result_payload["rows"]:
        assert set(row) == set(COMPACT_ROSTER_FIELDS)
        assert "worktrees" not in row


def test_unpaged_request_keeps_the_legacy_shape(test_db):
    _seed_ladder(test_db, 2, first_id=930)
    outcome = _roster()
    assert outcome.primary_success
    result = outcome.result_payload
    # Absent, not null: the unpaged reply is the shape it always was, so the
    # Overview frontier and the CLI adapter see no new keys at all.
    assert set(result) == {"rows", "count"}
    assert any("worktrees" in row for row in result["rows"])


def test_overview_relevance_cannot_be_combined_with_paging(test_db):
    outcome = _roster(relevance="overview", page_size=5)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "relevance" in outcome.error.message


def test_filtering_without_page_size_is_refused_by_name(test_db):
    outcome = _roster(search="anything")
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "page_size" in outcome.error.message


def test_malformed_cursor_names_its_recovery(test_db):
    outcome = _roster(page_size=5, cursor="not-a-cursor")
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "Reload the Items page" in outcome.error.message


def test_page_size_bounds_are_enforced(test_db):
    over = _roster(page_size=item_page_reads.MAX_ROSTER_PAGE_SIZE + 1)
    assert not over.primary_success
    assert over.error.code == "payload_invalid"
    assert not _roster(page_size=0).primary_success


def test_cursor_round_trips_its_stored_sort_value_verbatim():
    # A value with no trailing Z must come back byte-identical: normalizing it
    # would move the comparison the next page depends on.
    raw = "2026-09-08T02:19:40"
    assert decode_cursor(encode_cursor(raw, 42)) == (raw, 42)
    with pytest.raises(RosterCursorError):
        decode_cursor("missing-the-id|")


def test_paged_read_ships_a_fraction_of_the_unpaged_payload(test_db, capsys):
    """The measurement behind the change, kept as a regression guard.

    Reports honest numbers for both shapes over one identical dataset. Run
    with ``-s`` to read them; the assertions below are what keeps the payload
    from quietly growing back.
    """
    import json

    population = 300
    _seed_ladder(test_db, population, first_id=2000)
    unpaged = _roster()
    paged = _roster(page_size=50)
    assert unpaged.primary_success and paged.primary_success

    unpaged_rows = len(unpaged.result_payload["rows"])
    paged_rows = len(paged.result_payload["rows"])
    unpaged_bytes = len(json.dumps(unpaged.result_payload, default=str))
    paged_bytes = len(json.dumps(paged.result_payload, default=str))
    with capsys.disabled():
        print(
            f"\nItems roster payload over {unpaged_rows} matching items:"
            f"\n  before (unpaged): rows={unpaged_rows} bytes={unpaged_bytes}"
            f"\n  after  (paged):   rows={paged_rows} bytes={paged_bytes}"
            f" match_count={paged.result_payload['match_count']}"
            f"\n  bytes ratio: {paged_bytes / unpaged_bytes:.3f}"
            "\n  browser render time and per-request SQL attribution: "
            "not captured (missing, not zero)"
        )

    assert unpaged_rows >= population
    assert paged_rows == 50
    # The page reports the whole match set even though it carries 50 rows.
    assert paged.result_payload["match_count"] >= population
    # A page of 50 out of 300+ must cost well under a quarter of the full
    # transfer; the compact projection widens the gap beyond the row ratio.
    assert paged_bytes < unpaged_bytes / 4
