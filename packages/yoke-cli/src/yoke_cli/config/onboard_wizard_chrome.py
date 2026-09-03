"""Header and footer chrome for the ``yoke onboard`` wizard shell."""

from __future__ import annotations

import sys

from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import ACCENT, DIM, TEXT


def _footer_hint(glyph: str, label: str) -> str:
    """One footer hint: a bright key glyph and its dim label."""
    return f"[{TEXT}]{glyph}[/] [{DIM}]{label}[/]"


# Key glyphs render bright, their labels dim, so the keys read at a glance while
# the labels recede.
_MOUSE_REPORTING_OFF = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"


def header() -> str:
    marks = glyphs()
    return (
        f"[bold {ACCENT}]{marks.header_mark} Yoke[/]  "
        f"[#7d8590]{marks.header_sep} "
        "Set up your machine and onboard your projects[/]"
    )


def footer() -> str:
    marks = glyphs()
    return "     ".join(
        _footer_hint(glyph, label)
        for glyph, label in (
            (marks.footer_navigate, "navigate"),
            (marks.footer_select, "select"),
            ("esc", "back"),
            ("^c", "quit"),
        )
    )


def disable_mouse_reporting() -> None:
    sys.stdout.write(_MOUSE_REPORTING_OFF)
    sys.stdout.flush()


__all__ = ["disable_mouse_reporting", "footer", "header"]
