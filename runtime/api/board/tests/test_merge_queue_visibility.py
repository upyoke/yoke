"""Board item and session rows expose the merge-queue handoff."""

from yoke_contracts.board.sections import ItemRow, render_section


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
