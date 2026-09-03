"""Keyboard scrolling for the wizard body.

The body is a non-focusable scroll container, so its own scroll bindings never
sit on the focus chain when nothing is focused (a checking screen) and the
arrow keys belong to the focused list when one is. These app-level actions give
every step the same scroll keys: PageUp/PageDown, Home/End, and the arrows on
a screen with no list to move through. The wheel and the scrollbar reach the
same container through Textual's mouse handling.
"""

from __future__ import annotations

from typing import Any, Protocol

from textual.containers import VerticalScroll

BODY_ID = "onboard-body"


class _Shell(Protocol):  # pragma: no cover - structural typing only
    def query_one(self, selector: str, expect_type: Any = None) -> Any: ...


class BodyScrollFlow:
    def _scrolling_body(self: _Shell) -> VerticalScroll:
        return self.query_one(f"#{BODY_ID}", VerticalScroll)

    def action_body_page_up(self: _Shell) -> None:
        self._scrolling_body().action_page_up()

    def action_body_page_down(self: _Shell) -> None:
        self._scrolling_body().action_page_down()

    def action_body_line_up(self: _Shell) -> None:
        self._scrolling_body().action_scroll_up()

    def action_body_line_down(self: _Shell) -> None:
        self._scrolling_body().action_scroll_down()

    def action_body_home(self: _Shell) -> None:
        self._scrolling_body().action_scroll_home()

    def action_body_end(self: _Shell) -> None:
        self._scrolling_body().action_scroll_end()


__all__ = ["BODY_ID", "BodyScrollFlow"]
