"""Board item rows keep merge-queue diagnostics out of the status cell."""

from yoke_contracts.board.sections import ItemRow, render_section


def test_item_status_cell_shows_lifecycle_status_after_queue_landing():
    item = ItemRow(
        rank=1,
        id="YOK-7",
        title="Landed work awaiting close-out",
        workflow_id="dash",
        priority="high",
        status="implementing",
        progress="—",
        epic_id=None,
        project="yoke",
        updated_at="2026-08-27T18:00:00Z",
        merge_queue_status=(
            "merge queue landed at 2026-08-27T18:00:00Z; close-out pending"
        ),
    )
    rendered = render_section("Active", [item], {}, object(), "", 7)
    assert "🔨 implementing" in rendered
    assert "merge queue landed" not in rendered
