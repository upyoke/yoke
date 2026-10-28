"""Textual shell for the fixed-frame, keyboard-driven onboarding wizard.

Per-step bodies and decision transitions live in focused sibling modules.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Rule, Static

from yoke_cli.config.onboard_terminal import (
    plain_glyphs,
    plain_text,
    screen_compat_terminal,
)
from yoke_cli.config import onboard_wizard_chrome as chrome
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_body_scroll import BODY_ID, BodyScrollFlow
from yoke_cli.config.onboard_wizard_body_swap import BodySwap
from yoke_cli.config.onboard_wizard_checking import CheckingFlow
from yoke_cli.config.onboard_wizard_copy_open import CopyOpenFlow
from yoke_cli.config.onboard_wizard_flows import SETUP_FLOWS, init_setup_state
from yoke_cli.config.onboard_wizard_input_entry import InputEntry
from yoke_cli.config.onboard_wizard_redraw import FullFrameRedraw
from yoke_cli.config.onboard_wizard_state import _PendingForm, _PendingInput, _View
from yoke_cli.config.onboard_wizard_widgets import SelectionList, Stepper


class OnboardWizardApp(
    CheckingFlow,
    *SETUP_FLOWS,
    InputEntry,
    BodyScrollFlow,
    BodySwap,
    CopyOpenFlow,
    FullFrameRedraw,
    App[None],
):
    CSS_PATH = "onboard_wizard.tcss"
    # The arrow bindings only reach the body when no list or input is focused:
    # a focused SelectionList sits earlier on the binding chain and keeps them.
    # The copy and open chords take priority so they still reach the shell from
    # a screen whose text box holds focus.
    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("ctrl+[", "back", "back", show=False),
        Binding("ctrl+c", "quit_wizard", "quit", show=False, priority=True),
        Binding(chrome.COPY_KEY, "copy_target", "copy", show=False, priority=True),
        Binding(chrome.OPEN_KEY, "open_target", "open", show=False, priority=True),
        Binding("pageup", "body_page_up", "scroll up", show=False),
        Binding("pagedown", "body_page_down", "scroll down", show=False),
        Binding("up", "body_line_up", "scroll up", show=False),
        Binding("down", "body_line_down", "scroll down", show=False),
        Binding("home", "body_home", "top", show=False),
        Binding("end", "body_end", "bottom", show=False),
    ]

    def __init__(
        self,
        *,
        defaults: WizardDefaults,
        apply_report: Callable[..., Any],
    ) -> None:
        super().__init__()
        init_setup_state(self, defaults=defaults, apply_report=apply_report)
        self._pending_input: _PendingInput | None = None
        self._pending_form: _PendingForm | None = None
        # Set by ``_render_current`` and drained by the async message handlers so
        # the body swap runs in the same handler turn as the transition keypress.
        self._swap_pending = False
        self._screen_compat = screen_compat_terminal()
        self._plain_glyphs = plain_glyphs()

    def compose(self) -> ComposeResult:
        yield Static(chrome.header(), id="onboard-header", markup=True)
        yield Stepper(id="onboard-stepper")
        yield self._divider()
        # Non-focusable: a scroll container that can take focus would steal it
        # from the active SelectionList/Input on a body click and leave Enter
        # dead. on_click then refocuses the active control for header/footer/
        # label clicks too. Plain-glyph terminals hide the scrollbar in the
        # stylesheet and keep the keyboard scroll keys.
        yield VerticalScroll(id=BODY_ID, can_focus=False)
        yield self._divider()
        yield Static(chrome.footer(), id="onboard-footer", markup=True)

    def _divider(self) -> Rule | Static:
        if self._screen_compat or self._plain_glyphs:
            return Static("", classes="onboard-divider")
        return Rule(classes="onboard-divider")

    async def on_mount(self) -> None:
        if self._plain_glyphs:
            self.screen.add_class("plain-glyphs")
        self._start_front()
        await self._apply_pending_swap()

    # ── flow control ────────────────────────────────────────

    def _goto(self, view: _View) -> None:
        self._attach_carried_details(view)
        self._disclose_permissions(view)
        self._history.append(view)
        self._render_current()

    def _replace_current(self, view: _View) -> None:
        """Swap the current view in place without growing history (Applying ->
        success/failure), so a later Esc never lands on a non-interactive screen."""
        self._attach_carried_details(view)
        if self._history:
            self._history[-1] = view
        else:
            self._history.append(view)
        self._render_current()

    def _render_current(self) -> None:
        # Mark a swap as pending and disable the outgoing input *now*, before any
        # await yields control back to the message loop. A still-focused outgoing
        # Input would otherwise swallow a keystroke typed during the transition
        # (the leading "~" of a path is the painful case); disabling it drops its
        # focus immediately so no key lands in a widget that is about to vanish.
        self._pending_input = None
        self._pending_form = None
        self._swap_pending = True
        body = self.query_one(f"#{BODY_ID}")
        for widget in body.children:
            if isinstance(widget, Input):
                widget.disabled = True
        # The async message handlers drain the swap synchronously in the same
        # handler turn the transition keypress drove (so there is never an idle
        # tick where the new input is unmounted yet keys can still be dispatched).
        # This next-tick fallback covers any path that reaches _render_current
        # outside a draining handler — chiefly tests that call a flow method
        # directly — so the swap still settles on the next message-loop tick.
        self.call_later(self._apply_pending_swap)

    def _refocus_body(self) -> None:
        """Move focus to the body's first focusable child (SelectionList/Input).

        The body is a non-focusable VerticalScroll or plain-glyph Vertical.
        Empty body space would otherwise clear focus off the active list,
        leaving the highlighted row while Enter silently no-ops. Re-running
        the body mount focus rule keeps Enter live after any click.
        """
        body = self.query_one(f"#{BODY_ID}")
        self._focus_first(list(body.children))

    def on_click(self, event: Any) -> None:
        # Any click that lands on the body chrome (the non-focusable scroll
        # container, the header/stepper/footer, or a static label) restores
        # focus to the active control so Enter never goes dead.
        self._refocus_body()

    def _plainify_widgets(self, widgets: list[Static]) -> None:
        for widget in widgets:
            if isinstance(widget, Static) and not isinstance(widget, Stepper):
                widget.update(plain_text(str(widget.render())))
            if isinstance(widget, Input):
                widget.placeholder = plain_text(str(widget.placeholder or ""))

    def _focus_first(self, widgets: list[Static]) -> Static | None:
        for widget in widgets:
            if isinstance(widget, (SelectionList, Input)):
                self.set_focus(widget)
                return widget
        return None

    async def action_back(self) -> None:
        if self._checking:
            # A check that named a cancel route (the browser-approval wait)
            # is abandoned and routes itself; any other check keeps Esc idle.
            if self._cancel_checking():
                await self._apply_pending_swap()
            return
        self._step_back()
        await self._apply_pending_swap()

    def _step_back(self) -> None:
        if not self._applying and len(self._history) > 1:
            self._history.pop()
            self._render_current()

    def action_quit_wizard(self) -> None:
        # Apply is an atomic worker-thread transaction that can't be killed mid-
        # flight; quitting here is the mid-mutation cliff (after clone, before
        # push) onboarding must avoid. Suppress quit while applying — the worker
        # finalizes the report and routes to success/failure, where Exit lives.
        if self._applying or self._checking_blocks_quit:
            return
        self.cancelled = True
        self.exit_code = 130
        self.exit()

    # ── message routing ─────────────────────────────────────

    async def on_selection_list_selected(self, message: SelectionList.Selected) -> None:
        handler = self._history[-1].on_select
        if handler is not None:
            handler(message.value)
        await self._apply_pending_swap()


__all__ = ["OnboardWizardApp"]
