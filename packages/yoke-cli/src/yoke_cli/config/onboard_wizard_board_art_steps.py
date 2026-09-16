"""Board-art body builders and option rows for the onboarding wizard.

Split out of :mod:`onboard_wizard_steps` to keep each authored module under the
line budget. These build the board-art step's screens (style picker, preview,
gallery) and reuse the shared ``_heading`` primitive from the steps module.
Consumed by :class:`onboard_wizard_flow_board_art.BoardArtFlow`.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from yoke_cli.config.onboard_wizard_steps import _heading
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

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
        Text(art_text, no_wrap=True),
        markup=False,
        classes="onboard-art",
    )


def art_screen_body(
    title: str,
    subtitle: str | None,
    art_text: str,
    rows: list[SelectionRow],
) -> list[Static]:
    """A board-art screen: heading, the rendered art, then the option rows."""
    return [
        *_heading(title, subtitle),
        _art_block(art_text),
        Static("", classes="onboard-spacer"),
        SelectionList(rows),
    ]


def board_art_gallery_body(
    variants: list[Any], *, details: bool = False
) -> list[Static]:
    count = len(variants)
    counts: dict[str, int] = {}
    for variant in variants:
        kind = str(getattr(variant, "kind", "Header"))
        counts[kind] = counts.get(kind, 0) + 1
    recent = variants[-1]
    widgets = _heading(
        f"Your headers — {count} saved.",
        "Each rebuild rotates the progress map and these headers.",
    )
    widgets.append(
        Static(
            "By style: "
            + " · ".join(f"{kind} {total}" for kind, total in sorted(counts.items())),
            classes="onboard-plan-line",
        )
    )
    widgets.append(
        Static(
            f"Most recent: {getattr(recent, 'kind', 'Header')} · {getattr(recent, 'word', '') or 'project default'}",
            classes="onboard-plan-line",
        )
    )
    if details:
        for index, variant in enumerate(variants, start=1):
            bits = [
                str(variant.kind),
                f'"{getattr(variant, "word", "") or "project default"}"',
            ]
            if getattr(variant, "font", None):
                bits.append(str(variant.font))
            widgets.append(
                Static(f"  {index}. " + " · ".join(bits), classes="onboard-plan-line")
            )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = [
        SelectionRow("continue", "Continue", f"{count} headers saved"),
        SelectionRow("another", "Add another", "back to styles"),
        SelectionRow(
            "details",
            "Hide saved headers" if details else "Review saved headers",
            "exact list and removal controls",
        ),
    ]
    if details:
        rows.extend(
            SelectionRow(
                f"remove:{index}",
                f"Remove header {index + 1}",
                "delete this saved variant",
            )
            for index in range(count)
        )
    widgets.append(SelectionList(rows))
    return widgets


__all__ = [
    "BOARD_ART_IMAGE_RETRY_ROWS",
    "BOARD_ART_STYLE_ROWS",
    "art_screen_body",
    "board_art_gallery_body",
]
