"""Selection rows retain full labels and hints at every terminal width."""

from __future__ import annotations

import asyncio

import pytest
from rich.cells import cell_len

from yoke_cli.config.onboard_destination_rows import (
    DESTINATION_ROWS,
    SELF_HOST_SERVER_ROW,
)
from yoke_cli.config.onboard_wizard_widgets import (
    _OptionRow,
    _option_row_text,
)
from yoke_cli.config.setup_prompt import SelectionRow

SELF_HOST_ROW = next(
    row for row in DESTINATION_ROWS if row.value == SELF_HOST_SERVER_ROW
)


def test_long_hint_moves_below_the_full_label() -> None:
    # Label, gap and hint need 67 cells; 60 forces the hint onto its own line.
    rendered = _option_row_text(SELF_HOST_ROW, selected=True, width=60)
    assert rendered.plain == f"›  {SELF_HOST_ROW.label}\n{SELF_HOST_ROW.hint}"


def test_short_selection_row_keeps_its_hint_right_aligned() -> None:
    row = SelectionRow("back", "Back", "choose another Yoke home")
    rendered = _option_row_text(row, selected=False, width=70)
    assert "\n" not in rendered.plain
    assert cell_len(rendered.plain) == 70
    assert rendered.plain.endswith(row.hint)


@pytest.mark.parametrize("columns", [40, 60, 80, 100, 120, 143])
def test_every_destination_row_keeps_all_text_at_common_widths(monkeypatch, columns):
    pytest.importorskip("textual")
    from runtime.api.cli.onboard_wizard_test_helpers import (
        advance_past_path,
        make_app,
        stub_path_doctor,
    )
    from yoke_cli.config.onboard_wizard import WizardDefaults

    stub_path_doctor(monkeypatch)
    app, _spy = make_app(
        WizardDefaults(
            config_path="/tmp/cfg.json", env_name=None, api_url=None, token=None
        )
    )

    async def scenario() -> list[tuple[str, int, int]]:
        async with app.run_test(size=(columns, 32)) as pilot:
            await advance_past_path(pilot)
            await pilot.pause()
            return [
                (str(row.render()), row.content_size.width, row.size.height)
                for row in app.query(_OptionRow)
            ]

    rows = asyncio.run(scenario())
    assert len(rows) == len(DESTINATION_ROWS)
    for (line, width, height), row in zip(rows, DESTINATION_ROWS):
        assert height >= 1
        assert row.label in line
        assert row.hint in line
        assert "…" not in line
        # Every hint fits intact beside its label from 100 columns up.
        if columns >= 100:
            assert line.endswith(row.hint), (columns, row.label, line)


@pytest.mark.parametrize("width", [0, 1, 3, 12, 30, 70])
def test_long_label_and_hint_are_never_truncated(width):
    rendered = _option_row_text(SELF_HOST_ROW, selected=True, width=width)
    assert SELF_HOST_ROW.label in rendered.plain
    assert SELF_HOST_ROW.hint in rendered.plain
