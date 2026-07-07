"""Board-art body builders and option rows for the onboarding wizard.

Split out of :mod:`onboard_wizard_steps` to keep each authored module under the
line budget. These build the board-art step's screens (style picker, preview,
gallery, payoff) and reuse the shared ``_heading`` primitive from the steps
module. Consumed by :class:`onboard_wizard_flow_board_art.BoardArtFlow`.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from yoke_cli.config.onboard_wizard_palette import ACCENT
from yoke_cli.config.onboard_wizard_steps import _heading
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

BOARD_ART_INTRO_ROWS = [
    SelectionRow("design", "Let's design it", "a progress map + at least one header"),
]

BOARD_ART_STYLE_ROWS = [
    SelectionRow("ascii", "ASCII", "bold figlet lettering"),
    SelectionRow("mixed", "Mixed", "lettering + an emoji column"),
    SelectionRow("image", "From an image", "turn a PNG/JPG into emoji"),
]

BOARD_ART_IMAGE_RETRY_ROWS = [
    SelectionRow("retry", "Try another image", ""),
    SelectionRow("back", "Back to styles", ""),
]


def _art_block(art_text: str) -> Static:
    # The art carries figlet glyphs (literal ``[``) and double-width emoji, so it
    # must render as a plain Rich Text with markup disabled and no soft-wrap; the
    # ``onboard-art`` rule lets a too-wide row scroll rather than reflow.
    return Static(
        Text(art_text, no_wrap=True), markup=False, classes="onboard-art",
    )


def art_screen_body(
    title: str, subtitle: str | None, art_text: str, rows: list[SelectionRow],
) -> list[Static]:
    """A board-art screen: heading, the rendered art, then the option rows."""
    return [
        *_heading(title, subtitle),
        _art_block(art_text),
        Static("", classes="onboard-spacer"),
        SelectionList(rows),
    ]


def board_art_gallery_body(variants: list[Any]) -> list[Static]:
    count = len(variants)
    noun = "header" if count == 1 else "headers"
    widgets = _heading(
        f"Your headers — {count} saved.",
        "Add more, or continue. Each rebuild rotates the map and your headers.",
    )
    for index, variant in enumerate(variants, start=1):
        bits = [variant.kind]
        if getattr(variant, "word", ""):
            bits.append(f'"{variant.word}"')
        if getattr(variant, "font", None):
            bits.append(variant.font)
        widgets.append(
            Static(f"  {index}. " + " · ".join(bits), classes="onboard-plan-line")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = [SelectionRow("another", "Generate another", "back to styles")]
    if count >= 1:
        rows.append(SelectionRow("continue", "Continue", f"{count} {noun} saved"))
    widgets.append(SelectionList(rows))
    return widgets


def board_art_payoff_body(
    rendered: str, count: int,
) -> list[Static]:
    noun = "header" if count == 1 else "headers"
    return [
        Static(f"[{ACCENT}]✓ Your board is ready.[/]", classes="onboard-title"),
        Static(
            "Saved .yoke/board-art and rebuilt your board.",
            classes="onboard-subtitle",
        ),
        Static("", classes="onboard-spacer"),
        _art_block(rendered),
        Static("", classes="onboard-spacer"),
        Static(
            f"It rotates with your {count} saved {noun} as work flows. "
            "Open it any time with `yoke board`.",
            classes="onboard-note",
        ),
        SelectionList([SelectionRow("finish", "Finish", "")]),
    ]


__all__ = [
    "BOARD_ART_IMAGE_RETRY_ROWS",
    "BOARD_ART_INTRO_ROWS",
    "BOARD_ART_STYLE_ROWS",
    "art_screen_body",
    "board_art_gallery_body",
    "board_art_payoff_body",
]
