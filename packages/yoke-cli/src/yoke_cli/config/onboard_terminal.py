"""Terminal capability helpers for the onboard wizard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class OnboardGlyphs:
    header_mark: str
    header_sep: str
    footer_navigate: str
    footer_select: str
    step_done: str
    step_active: str
    step_pending: str
    step_connector: str
    selected: str
    unselected: str
    bullet: str
    ok: str
    fail: str
    arrow: str
    apply_pending: str
    apply_running: str
    apply_done: str
    apply_skipped: str
    apply_failed: str


RICH_GLYPHS = OnboardGlyphs(
    header_mark="☀",
    header_sep="·",
    footer_navigate="↑↓",
    footer_select="↵",
    step_done="✔",
    step_active="●",
    step_pending="○",
    step_connector="───",
    selected="›",
    unselected="·",
    bullet="•",
    ok="✓",
    fail="✗",
    arrow="→",
    apply_pending="○",
    apply_running="◐",
    apply_done="✔",
    apply_skipped="⊘",
    apply_failed="✗",
)

PLAIN_GLYPHS = OnboardGlyphs(
    header_mark="*",
    header_sep="-",
    footer_navigate="up/down",
    footer_select="enter",
    step_done="+",
    step_active="*",
    step_pending="o",
    step_connector="---",
    selected=">",
    unselected="-",
    bullet="-",
    ok="OK",
    fail="x",
    arrow="->",
    apply_pending="o",
    apply_running="~",
    apply_done="+",
    apply_skipped="-",
    apply_failed="x",
)

_PLAIN_REPLACEMENTS = {
    "☀": PLAIN_GLYPHS.header_mark,
    "·": PLAIN_GLYPHS.header_sep,
    "↑↓": PLAIN_GLYPHS.footer_navigate,
    "↵": PLAIN_GLYPHS.footer_select,
    "✔": PLAIN_GLYPHS.ok,
    "✓": PLAIN_GLYPHS.ok,
    "✗": PLAIN_GLYPHS.fail,
    "●": PLAIN_GLYPHS.step_active,
    "○": PLAIN_GLYPHS.step_pending,
    "◐": PLAIN_GLYPHS.apply_running,
    "⊘": PLAIN_GLYPHS.apply_skipped,
    "›": PLAIN_GLYPHS.selected,
    "•": PLAIN_GLYPHS.bullet,
    "→": PLAIN_GLYPHS.arrow,
    "▌": "|",
    "───": PLAIN_GLYPHS.step_connector,
    "─": "-",
    "│": "|",
    "┃": "|",
    "━": "-",
    "═": "-",
    "—": "-",
    "–": "-",
    "…": "...",
}


def screen_compat_terminal(env: Mapping[str, str] | None = None) -> bool:
    values = env or os.environ
    term = str(values.get("TERM") or "").lower()
    return bool(values.get("STY")) or term == "screen" or term.startswith("screen-")


def plain_glyphs(env: Mapping[str, str] | None = None) -> bool:
    values = env or os.environ
    forced = str(values.get("YOKE_ONBOARD_FORCE_PLAIN") or "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    term = str(values.get("TERM") or "").lower()
    return screen_compat_terminal(values) or term == "dumb"


def glyphs(env: Mapping[str, str] | None = None) -> OnboardGlyphs:
    return PLAIN_GLYPHS if plain_glyphs(env) else RICH_GLYPHS


def plain_text(text: str) -> str:
    rendered = text
    for old, new in _PLAIN_REPLACEMENTS.items():
        rendered = rendered.replace(old, new)
    return rendered


__all__ = [
    "OnboardGlyphs",
    "PLAIN_GLYPHS",
    "RICH_GLYPHS",
    "glyphs",
    "plain_glyphs",
    "plain_text",
    "screen_compat_terminal",
]
