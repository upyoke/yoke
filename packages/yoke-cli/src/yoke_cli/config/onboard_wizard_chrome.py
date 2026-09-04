"""Header and footer chrome for the ``yoke onboard`` wizard shell."""

from __future__ import annotations

from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import ACCENT, DIM, TEXT


def _footer_hint(glyph: str, label: str) -> str:
    """One footer hint: a bright key glyph and its dim label."""
    return f"[{TEXT}]{glyph}[/] [{DIM}]{label}[/]"


# Key glyphs render bright, their labels dim, so the keys read at a glance while
# the labels recede.

# Both keys are control chords so they reach the shell even while a text box
# holds focus — the Hosting credential screen shows a URL beside its input.
COPY_KEY = "ctrl+y"
OPEN_KEY = "ctrl+o"
COPY_KEY_GLYPH = "^y"
OPEN_KEY_GLYPH = "^o"


def header() -> str:
    marks = glyphs()
    return (
        f"[bold {ACCENT}]{marks.header_mark} Yoke[/]  "
        f"[#7d8590]{marks.header_sep} "
        "Set up your machine and onboard your projects[/]"
    )


def footer(
    *,
    copy_label: str | None = None,
    open_label: str | None = None,
    note: str | None = None,
) -> str:
    """Render the key hints, with the copy/open keys only where they act.

    ``note`` leads the line: it reports what the last copy or open key press
    did, and belongs where the operator's eye already is.
    """
    marks = glyphs()
    hints = [
        (marks.footer_navigate, "navigate"),
        (marks.footer_select, "select"),
    ]
    if copy_label:
        hints.append((COPY_KEY_GLYPH, copy_label))
    if open_label:
        hints.append((OPEN_KEY_GLYPH, open_label))
    hints.extend((("esc", "back"), ("^c", "quit")))
    line = "     ".join(_footer_hint(glyph, label) for glyph, label in hints)
    if not note:
        return line
    return f"[{ACCENT}]{note}[/]     {line}"


__all__ = [
    "COPY_KEY",
    "COPY_KEY_GLYPH",
    "OPEN_KEY",
    "OPEN_KEY_GLYPH",
    "footer",
    "header",
]
