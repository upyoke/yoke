"""Overview item window: live work plus terminals finished in the last 24h."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import request_for
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import (
    DISPLAY_LABEL_SURFACE,
    seed_human_actor,
    set_actor_label,
)
from yoke_core.domain.handlers import item_page_reads, items_listing


def _iso(hours_ago: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _titles(outcome) -> set[str]:
    return {row["title"] for row in outcome.result_payload["rows"]}


def test_overview_keeps_live_and_recent_terminals(test_db):
    old = _iso(48)
    recent = _iso(2)
    insert_item(
        test_db, id=501, title="live-old", status="implementing",
        created_at=old, updated_at=old,
    )
    insert_item(
        test_db, id=502, title="done-recent", status="done",
        created_at=old, updated_at=old, merged_at=recent,
    )
    insert_item(
        test_db, id=503, title="done-old", status="done",
        created_at=old, updated_at=old, merged_at=old,
    )
    insert_item(
        test_db, id=504, title="cancelled-recent", status="cancelled",
        created_at=old, updated_at=recent,
    )
    test_db.commit()

    listing = items_listing.handle_items_list(
        request_for("items.list.run", {"fields": ["title"], "relevance": "overview"})
    )
    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {})
    )
    assert listing.primary_success and overview.primary_success
    expected = {"live-old", "done-recent", "cancelled-recent"}
    assert expected <= _titles(listing)
    assert expected <= _titles(overview)
    assert "done-old" not in _titles(listing)
    assert "done-old" not in _titles(overview)


def test_overview_resolves_each_owner_once(test_db, monkeypatch):
    actor_id = seed_human_actor(test_db)
    set_actor_label(test_db, actor_id, "Ada", surface=DISPLAY_LABEL_SURFACE)
    old = _iso(48)
    for item_id, title in ((601, "owned-a"), (602, "owned-b")):
        insert_item(
            test_db, id=item_id, title=title, status="implementing",
            owner=str(actor_id), created_at=old, updated_at=old,
        )
    test_db.commit()
    calls: list[int] = []
    real = actor_display_name

    def counted(conn, value):
        calls.append(int(value))
        return real(conn, value)

    monkeypatch.setattr(
        "yoke_core.domain.actor_display.actor_display_name", counted,
    )
    outcome = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {})
    )
    assert outcome.primary_success
    owners = {
        row["owner"]
        for row in outcome.result_payload["rows"]
        if row["title"] in {"owned-a", "owned-b"}
    }
    assert owners == {"Ada"}
    assert calls.count(actor_id) == 1
