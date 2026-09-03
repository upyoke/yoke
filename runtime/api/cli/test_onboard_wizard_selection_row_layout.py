"""Width-aware layout coverage for onboarding selection rows.

Every row is exactly one line wide: a hint that fits is right-aligned, a
hint that does not is cut to the room left and ends in an ellipsis, and a
hint with almost no room is dropped. No row wraps its hint under the label.
"""

from __future__ import annotations

import asyncio

import pytest
from rich.cells import cell_len

from yoke_cli.config.onboard_destination_rows import (
    DESTINATION_ROWS,
    SELF_HOST_SERVER_ROW,
)
from yoke_cli.config.onboard_wizard_widgets import (
    SelectionRow,
    _OptionRow,
    _option_row_text,
)

SELF_HOST_ROW = next(row for row in DESTINATION_ROWS if row.value == SELF_HOST_SERVER_ROW)


def test_a_hint_with_no_room_is_cut_to_an_ellipsis_on_the_same_line() -> None:
    rendered = _option_row_text(SELF_HOST_ROW, selected=True, width=70)

    assert rendered.plain.count("\n") == 0
    assert cell_len(rendered.plain) == 70
    assert rendered.plain.endswith("…")
    assert rendered.plain.startswith("›  Set this machine up as a self-hosting server ")


def test_short_selection_row_stays_on_one_line() -> None:
    rendered = _option_row_text(
        SelectionRow("back", "Back", "choose another Yoke home"),
        selected=False,
        width=70,
    )

    assert rendered.plain.count("\n") == 0
    assert cell_len(rendered.plain) == 70


def test_a_hint_with_almost_no_room_is_dropped_rather_than_stubbed() -> None:
    rendered = _option_row_text(
        SelectionRow("x", "A label that fills the whole row", "hint"),
        selected=False,
        width=36,
    )

    assert rendered.plain.rstrip() == "·  A label that fills the whole row"
    assert cell_len(rendered.plain) == 36


@pytest.mark.parametrize("columns", [100, 120, 143])
def test_every_destination_row_is_one_line_at_common_widths(monkeypatch, columns):
    pytest.importorskip("textual")
    from runtime.api.cli.onboard_wizard_test_helpers import (
        advance_past_path,
        make_app,
        stub_path_doctor,
    )
    from yoke_cli.config.onboard_wizard import WizardDefaults

    stub_path_doctor(monkeypatch)
    app, _spy = make_app(WizardDefaults(config_path="/tmp/cfg.json", env_name=None, api_url=None, token=None))

    async def scenario() -> list[tuple[str, int, int]]:
        async with app.run_test(size=(columns, 32)) as pilot:
            await advance_past_path(pilot)
            await pilot.pause()
            return [
                (str(row.render()), row.size.width, row.size.height)
                for row in app.query(_OptionRow)
            ]

    rows = asyncio.run(scenario())
    assert len(rows) == len(DESTINATION_ROWS)
    for (line, width, height), row in zip(rows, DESTINATION_ROWS):
        assert height == 1
        assert "\n" not in line
        assert cell_len(line) == width, (columns, row.label, line)
        # Every hint fits intact beside its label from 100 columns up.
        assert line.endswith(row.hint), (columns, row.label, line)
