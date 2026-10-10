"""Board item rows keep merge-queue diagnostics out of the status cell."""

from datetime import datetime

import pytest

from yoke_contracts.board.sections import ItemRow, render_section
from yoke_contracts.merge_queue_status import render_merge_queue_status
from yoke_contracts.timestamps import InvalidInstant, parse_instant


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


@pytest.mark.parametrize(
    "clock",
    [
        parse_instant("1969-12-31T23:59:59.123456Z"),
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
    ],
)
def test_queue_status_formats_only_its_owned_clock_text(clock):
    wire = "1969-12-31T23:59:59.123456Z"
    assert render_merge_queue_status(clock, None) == f"in merge queue since {wire}"
    assert render_merge_queue_status(clock, clock) == (
        f"merge queue landed at {wire}; close-out pending"
    )


@pytest.mark.parametrize("empty", [None, ""])
def test_queue_status_keeps_known_absence_and_closed_out_status(empty):
    assert render_merge_queue_status(empty, None) == ""
    assert render_merge_queue_status(None, empty) == ""
    clock = parse_instant("1969-12-31T23:59:59.123456Z")
    for status in ("done", "cancelled"):
        assert render_merge_queue_status(clock, clock, item_status=status) == ""


@pytest.mark.parametrize(
    "bad", ["1969-12-31", "1969-12-31T23:59:59", "invalid", datetime(1969, 12, 31)]
)
def test_queue_status_refuses_ambiguous_display_clocks(bad):
    clock = parse_instant("1969-12-31T23:59:59.123456Z")
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        render_merge_queue_status(bad, None)
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        render_merge_queue_status(clock, bad)
