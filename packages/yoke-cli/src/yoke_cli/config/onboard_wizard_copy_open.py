"""Copy and open the exact URL or one-time code the current screen shows.

A one-time code and a long sign-in URL are the two things onboarding asks a
person to carry out of the terminal by hand, and a wrapped URL retyped or
re-selected is where that goes wrong. Every screen showing one registers it as
a :class:`CopyTarget`; the copy key puts it on the clipboard verbatim and the
open key hands a URL to the browser, each reporting what happened in the
footer where the key hints already are.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from textual.widgets import Static

from yoke_cli.config import onboard_clipboard
from yoke_cli.config import onboard_wizard_chrome as chrome
from yoke_cli.config.hosted_machine_browser import open_url
from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_state import CopyTarget

FOOTER_ID = "onboard-footer"

NOTHING_TO_COPY_NOTE = "Nothing to copy on this screen."
NOTHING_TO_OPEN_NOTE = "No link on this screen to open."


class _Shell(Protocol):  # pragma: no cover - structural typing only
    def query_one(self, selector: str, expect_type=None): ...


class CopyOpenFlow:
    """The shell's clipboard and browser keys, bound to the current view."""

    # Rebound on every body swap from the incoming view's declared targets.
    _copy_targets: tuple[CopyTarget, ...] = ()
    _copy_cursor: int = 0
    _footer_note: str | None = None

    def _set_copy_targets(self: _Shell, targets: Iterable[CopyTarget]) -> None:
        self._copy_targets = tuple(targets)
        self._copy_cursor = 0
        self._footer_note = None
        self._render_footer()

    def _render_footer(self: _Shell) -> None:
        self.query_one(f"#{FOOTER_ID}", Static).update(
            chrome.footer(
                copy_label=self._copy_hint_label(),
                open_label=self._open_hint_label(),
                note=self._footer_note,
            )
        )

    def _copy_hint_label(self: _Shell) -> str | None:
        target = self._current_copy_target()
        return f"copy {target.label}" if target else None

    def _open_hint_label(self: _Shell) -> str | None:
        target = self._current_open_target()
        return f"open {target.label}" if target else None

    def _current_copy_target(self: _Shell) -> CopyTarget | None:
        if not self._copy_targets:
            return None
        return self._copy_targets[self._copy_cursor % len(self._copy_targets)]

    def _current_open_target(self: _Shell) -> CopyTarget | None:
        return next(
            (target for target in self._copy_targets if target.is_url), None,
        )

    def _note(self: _Shell, text: str) -> None:
        self._footer_note = text
        self._render_footer()

    def action_copy_target(self: _Shell) -> None:
        """Copy the current target; a screen with several cycles through them."""
        target = self._current_copy_target()
        if target is None:
            self._note(NOTHING_TO_COPY_NOTE)
            return
        marks = glyphs()
        result = onboard_clipboard.copy(target.value)
        if not result.copied:
            self._note(f"{marks.fail} Couldn't copy {target.label}: {result.reason}")
            return
        # Advance first, so the footer hint now names what a second press takes
        # — that is how a screen carrying both a code and a URL advertises both.
        self._copy_cursor += 1
        self._note(f"{marks.ok} Copied {target.label}.")

    def action_open_target(self: _Shell) -> None:
        target = self._current_open_target()
        if target is None:
            self._note(NOTHING_TO_OPEN_NOTE)
            return
        marks = glyphs()
        result = open_url(target.value)
        if result.opened:
            self._note(f"{marks.ok} Opened {target.label} in your browser.")
            return
        self._note(f"{marks.fail} Couldn't open {target.label}: {result.reason}")


__all__ = ["CopyOpenFlow", "FOOTER_ID", "NOTHING_TO_COPY_NOTE", "NOTHING_TO_OPEN_NOTE"]
