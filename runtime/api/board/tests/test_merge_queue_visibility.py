"""Board item and session rows expose the merge-queue handoff."""

from yoke_contracts.board.sections import ItemRow, render_section
from yoke_contracts.board.sections_sessions_extra_claims import build_session_keycaps


def test_item_status_cell_shows_queue_admission():
    item = ItemRow(
        rank=1,
        id="YOK-7",
        title="Queued work",
        workflow_id="dash",
        priority="high",
        status="reviewing-implementation",
        progress="—",
        epic_id=None,
        project="yoke",
        updated_at="2026-08-27T18:00:00Z",
        merge_queue_status="in merge queue since 2026-08-27T18:00:00Z",
    )
    rendered = render_section("Active", [item], {}, object(), "", 7)
    assert "in merge queue since 2026-08-27T18:00:00Z" in rendered
    assert "🔨 reviewing-implementation" not in rendered


class _SessionBoard:
    def has_query_quiet(self, sql, params=None):
        return True

    def query_quiet(self, sql, params=None):
        if "merge_queue_enqueued_at" in sql:
            return [
                (
                    "reviewing-implementation",
                    "2026-08-27T18:00:00Z",
                    "",
                )
            ]
        return []

    def query(self, sql, params=None):
        return []


def test_session_claim_keycap_shows_queue_admission():
    keycaps = build_session_keycaps(
        _SessionBoard(),
        "session-1",
        [("YOK-7", 7, None)],
        active_only=True,
    )
    assert keycaps == ["YOK-7 · in merge queue since 2026-08-27T18:00:00Z"]
