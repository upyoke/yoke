"""Shared fixtures for the paged Items roster suites.

The roster's paging behaviour and its project-visibility boundary are
separate subjects with separate test modules, but both seed the same shaped
rows and dispatch the same read, so the seeding and dispatch live here once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import request_for
from yoke_core.domain.handlers import item_page_reads


def iso_minutes_ago(minutes: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_roster(actor_id="op", **payload):
    """Dispatch the roster read the way the product dispatches it."""
    return item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", payload, actor_id=actor_id)
    )


def public_refs(outcome) -> list[str]:
    return [row["public_ref"] for row in outcome.result_payload["rows"]]


def seed_ladder(test_db, count: int, *, first_id: int = 700) -> None:
    """Items whose update times descend with their ids, newest first."""
    for offset in range(count):
        insert_item(
            test_db,
            id=first_id + offset,
            title=f"ladder item {offset}",
            status="implementing",
            created_at=iso_minutes_ago(600),
            updated_at=iso_minutes_ago(500 - offset),
        )
    test_db.commit()


__all__ = [
    "iso_minutes_ago",
    "public_refs",
    "read_roster",
    "seed_ladder",
]
