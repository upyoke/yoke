"""Width-aware layout coverage for onboarding selection rows."""

from __future__ import annotations

from rich.cells import cell_len

from yoke_cli.config.onboard_destination_rows import (
    DESTINATION_ROWS,
    SELF_HOST_SERVER_ROW,
)
from yoke_cli.config.onboard_wizard_widgets import (
    SelectionRow,
    _option_row_text,
)


def test_long_destination_hint_wraps_intact_within_eighty_column_body() -> None:
    row = next(row for row in DESTINATION_ROWS if row.value == SELF_HOST_SERVER_ROW)

    rendered = _option_row_text(row, selected=True, width=70)

    lines = rendered.plain.splitlines()
    assert row.hint == "Docker Compose · guided first boot"
    assert row.hint in rendered.plain
    assert len(lines) == 2
    assert all(cell_len(line) <= 70 for line in lines)


def test_short_selection_row_stays_on_one_line() -> None:
    rendered = _option_row_text(
        SelectionRow("back", "Back", "choose another Yoke home"),
        selected=False,
        width=70,
    )

    assert rendered.plain.count("\n") == 0
    assert cell_len(rendered.plain) == 70
